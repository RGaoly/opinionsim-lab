"""PostgreSQL queue: short locks, budget reservations, leases, fenced commits."""
import os
import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from psycopg.types.json import Jsonb
from .db import connect, event
from .domain import render, reserve_cost, price

LEASE_SECONDS = 600


def claim():
    with connect() as c:
        experiments = c.execute('''SELECT e.* FROM experiments e WHERE status IN ('queued','running')
              AND EXISTS(SELECT 1 FROM tasks t WHERE t.experiment_id=e.id AND t.state IN ('queued','retry')
                         AND t.available_at<=now()) ORDER BY created_at LIMIT 20 FOR UPDATE SKIP LOCKED''').fetchall()
        for e in experiments:
            t = c.execute('''SELECT * FROM tasks WHERE experiment_id=%s AND state IN ('queued','retry')
                       AND available_at<=now() ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED''', (e['id'],)).fetchone()
            if not t:
                continue
            model = e['config']['models'][t['model_idx']]
            cred = None
            if model['provider'] != 'mock':
                if os.environ.get('ALLOW_PAID_API') != 'true' or e['authorized_at'] is None:
                    continue
                cred = c.execute('SELECT * FROM credentials WHERE id=%s FOR UPDATE', (model['credential_id'],)).fetchone()
                if not cred or not cred['active']:
                    c.execute("UPDATE experiments SET status='paused' WHERE id=%s", (e['id'],))
                    event(c, e['id'], 'credential_inactive')
                    continue
                if cred['next_allowed'] > datetime.now(timezone.utc):
                    continue
            person = c.execute('SELECT profile FROM participants WHERE dataset_id=%s AND rid=%s',
                               (e['dataset_id'], t['rid'])).fetchone()
            prompt = render(e['config'], t, person['profile'])
            reservation = reserve_cost(model, prompt, e['config']['max_output_tokens'])
            if e['spent'] + e['uncertain'] + e['reserved'] + reservation > e['budget']:
                if not e['reserved']:
                    c.execute("UPDATE experiments SET status='budget_blocked' WHERE id=%s", (e['id'],))
                    event(c, e['id'], 'budget_blocked', {'next_reservation': str(reservation)})
                continue
            token = uuid.uuid4()
            request = {'model': model['model'], 'messages': [{'role':'user','content':prompt}],
                       'max_tokens': e['config']['max_output_tokens'], **model.get('parameters', {})}
            c.execute('''UPDATE tasks SET state='running',attempts=attempts+1,claim_token=%s,
                      lease_until=now()+make_interval(secs=>%s),reservation=%s WHERE id=%s''',
                      (token, LEASE_SECONDS, reservation, t['id']))
            c.execute('''INSERT INTO attempts(task_id,number,claim_token,status,request,reservation)
                      VALUES (%s,%s,%s,'running',%s,%s)''',
                      (t['id'], t['attempts']+1, token, Jsonb(request), reservation))
            c.execute("UPDATE experiments SET reserved=reserved+%s,status='running' WHERE id=%s", (reservation,e['id']))
            if cred:
                c.execute('UPDATE credentials SET next_allowed=now()+make_interval(secs=>%s) WHERE id=%s',
                          (60.0 / cred['rpm'], cred['id']))
            t.update(claim_token=token, attempts=t['attempts']+1, reservation=reservation)
            return {'task':t,'experiment':e,'model':model,'credential':cred,'request':request}
    return None


def finish(job, outcome):
    t, e = job['task'], job['experiment']
    with connect() as c:
        c.execute('SELECT id FROM experiments WHERE id=%s FOR UPDATE', (e['id'],))
        current = c.execute('SELECT * FROM tasks WHERE id=%s FOR UPDATE', (t['id'],)).fetchone()
        if current['state'] != 'running' or current['claim_token'] != t['claim_token']:
            # Late response: preserve evidence for reconciliation; never settle twice.
            c.execute('UPDATE attempts SET response=coalesce(response,%s) WHERE claim_token=%s',
                      (Jsonb(outcome.get('response')), t['claim_token']))
            event(c,e['id'],'late_result',{'task_id':t['id']})
            return
        state = outcome['state']
        known_cost = Decimal('0')
        uncertain = Decimal('0')
        if state == 'succeeded':
            inp, out = outcome.get('input_tokens'), outcome.get('output_tokens')
            if inp is not None and out is not None:
                known_cost = price(job['model'],inp,out)
            else:
                uncertain = t['reservation']
        elif state == 'ambiguous':
            uncertain = t['reservation']
        if state == 'retry' and t['attempts'] >= 5:
            state = 'failed'
        delay = min(300, max(float(outcome.get('retry_after',0)), 2 ** t['attempts']))
        c.execute('''UPDATE tasks SET state=%s,lease_until=NULL,reservation=0,answer=%s,parse_error=%s,
                  available_at=now()+make_interval(secs=>%s) WHERE id=%s''',
                  (state,outcome.get('answer'),outcome.get('parse_error'),delay,t['id']))
        c.execute('''UPDATE attempts SET status=%s,response=%s,error_code=%s,input_tokens=%s,output_tokens=%s,
                  cost=%s,finished_at=now() WHERE claim_token=%s''',
                  (state,Jsonb(outcome.get('response')),outcome.get('error_code'),outcome.get('input_tokens'),
                   outcome.get('output_tokens'),known_cost if not uncertain else None,t['claim_token']))
        c.execute('''UPDATE experiments SET reserved=reserved-%s,spent=spent+%s,uncertain=uncertain+%s
                  WHERE id=%s''',(t['reservation'],known_cost,uncertain,e['id']))
        if known_cost > t['reservation']:
            c.execute("UPDATE experiments SET status='paused' WHERE id=%s",(e['id'],))
            event(c,e['id'],'reservation_exceeded',{'task_id':t['id']})
        if state != 'succeeded' or uncertain or outcome.get('parse_error'):
            event(c,e['id'],'task_'+state,{'task_id':t['id'],'code':outcome.get('error_code'),
                                         'parse_error':outcome.get('parse_error'),'uncertain':str(uncertain)})
        complete_if_done(c,e['id'])


def complete_if_done(c,eid):
    pending = c.execute("SELECT 1 FROM tasks WHERE experiment_id=%s AND state IN ('queued','retry','running') LIMIT 1",(eid,)).fetchone()
    if not pending:
        bad = c.execute("SELECT 1 FROM tasks WHERE experiment_id=%s AND (state!='succeeded' OR parse_error IS NOT NULL) LIMIT 1",(eid,)).fetchone()
        c.execute('UPDATE experiments SET status=%s WHERE id=%s',('completed_errors' if bad else 'completed',eid))


def recover_expired():
    # Fixed lock order everywhere: experiment -> tasks -> credentials.
    with connect() as c:
        expired = c.execute("SELECT DISTINCT experiment_id FROM tasks WHERE state='running' AND lease_until<now()").fetchall()
        for x in expired:
            eid = x['experiment_id']
            if not c.execute('SELECT id FROM experiments WHERE id=%s FOR UPDATE SKIP LOCKED',(eid,)).fetchone():
                continue
            tasks = c.execute("SELECT * FROM tasks WHERE experiment_id=%s AND state='running' AND lease_until<now() FOR UPDATE",(eid,)).fetchall()
            for t in tasks:
                c.execute("UPDATE tasks SET state='ambiguous',lease_until=NULL,reservation=0 WHERE id=%s",(t['id'],))
                c.execute("UPDATE attempts SET status='ambiguous',error_code='lease_expired',finished_at=now() WHERE claim_token=%s",(t['claim_token'],))
                c.execute('UPDATE experiments SET reserved=reserved-%s,uncertain=uncertain+%s WHERE id=%s',
                          (t['reservation'],t['reservation'],eid))
                event(c,eid,'lease_expired',{'task_id':t['id'],'policy':'manual_reconciliation'})
            complete_if_done(c,eid)
