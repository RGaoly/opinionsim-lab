import itertools
import os
import uuid
from psycopg.types.json import Jsonb
from .db import connect, rows, event
from .domain import canonical, sha, validate_config, validate_template
from .security import cipher, validate_endpoint


def create_project(name, notes=''):
    if not name.strip() or len(name) > 100:
        raise ValueError('项目名称必填，最多 100 字符')
    pid = uuid.uuid4()
    with connect() as c:
        c.execute('INSERT INTO projects(id,name,notes) VALUES (%s,%s,%s)', (pid, name.strip(), notes))
    return str(pid)


def save_dataset(pid, name, records, manifest):
    if not records:
        raise ValueError('不能保存空数据集')
    did = uuid.uuid4()
    with connect() as c:
        c.execute('INSERT INTO datasets VALUES (%s,%s,%s,%s,now())', (did, pid, name, Jsonb(manifest)))
        with c.cursor() as cur:
            cur.executemany('INSERT INTO participants VALUES (%s,%s,%s,%s)',
                            ((did, r['rid'], Jsonb(r['profile']), Jsonb(r['truth'])) for r in records))
        event(c, None, 'dataset_saved', {'dataset_id': str(did), 'rows': len(records), 'project_id': str(pid)})
    return str(did)


def save_prompt(pid, name, body, body_en=None):
    validate_template(body)
    if body_en:
        validate_template(body_en)
    if not name.strip():
        raise ValueError('提示语名称必填')
    with connect() as c:
        c.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE', (pid,))
        version = c.execute('SELECT coalesce(max(version),0)+1 AS v FROM prompts WHERE project_id=%s AND name=%s',
                            (pid, name)).fetchone()['v']
        c.execute('INSERT INTO prompts(id,project_id,name,version,body,body_en,sha256) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                  (uuid.uuid4(), pid, name, version, body, body_en, sha({'zh':body,'en':body_en})))


def save_credential(label, base_url, secret, rpm):
    if not label.strip() or not secret.strip():
        raise ValueError('密钥名称与 API Key 必填')
    base_url = validate_endpoint(base_url)
    with connect() as c:
        c.execute('''INSERT INTO credentials(id,label,base_url,ciphertext,rpm) VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT(label) DO UPDATE SET ciphertext=excluded.ciphertext,
                     base_url=excluded.base_url,rpm=excluded.rpm,active=true''',
                  (uuid.uuid4(), label.strip(), base_url, cipher().encrypt(secret.strip().encode()).decode(), rpm))
        event(c, None, 'credential_updated', {'label': label.strip()})


def create_experiment(pid, did, name, config, budget, eid=None):
    """Atomic creation; a stable caller UUID makes form retries idempotent."""
    from decimal import Decimal
    validate_config(config)
    budget = Decimal(str(budget))
    if not budget.is_finite() or budget < 0 or not name.strip():
        raise ValueError('实验名称和非负预算必填')
    eid = uuid.UUID(str(eid)) if eid else uuid.uuid4()
    digest = sha(config)
    with connect() as c:
        existing = c.execute('SELECT config_sha256 FROM experiments WHERE id=%s', (eid,)).fetchone()
        if existing:
            if existing['config_sha256'] != digest:
                raise ValueError('重复提交的实验配置不一致')
            return str(eid)
        dataset = c.execute('SELECT * FROM datasets WHERE id=%s AND project_id=%s', (did, pid)).fetchone()
        if not dataset:
            raise ValueError('数据集不属于当前项目')
        for m in config['models']:
            if m['provider'] == 'compatible':
                if not c.execute('SELECT id FROM credentials WHERE id=%s AND active', (m['credential_id'],)).fetchone():
                    raise ValueError('凭据不存在或已停用')
        count = c.execute('SELECT count(*) AS n FROM participants WHERE dataset_id=%s', (did,)).fetchone()['n']
        total = count * 96 * config['repetitions']
        if total > 1_000_000:
            raise ValueError('单实验上限 1,000,000 个任务，请拆分数据集')
        c.execute('''INSERT INTO experiments(id,project_id,dataset_id,name,config,config_sha256,currency,budget,total)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                  (eid, pid, did, name, Jsonb(config), digest, config['currency'], budget, total))
        rids = c.execute('SELECT rid FROM participants WHERE dataset_id=%s ORDER BY rid', (did,)).fetchall()
        params = ((eid, r['rid'], m, lang, p, q, rep) for r in rids
                  for m, lang, p, q, rep in itertools.product(range(2), ['zh','en'], range(4), range(6), range(config['repetitions'])))
        with c.cursor() as cur:
            cur.executemany('''INSERT INTO tasks(experiment_id,rid,model_idx,language,prompt_idx,question_idx,repetition)
                               VALUES (%s,%s,%s,%s,%s,%s,%s)''', params)
        event(c, eid, 'experiment_created', {'total': total, 'config_sha256': digest})
    return str(eid)


def control(eid, action, authorization=''):
    with connect() as c:
        e = c.execute('SELECT * FROM experiments WHERE id=%s FOR UPDATE', (eid,)).fetchone()
        if not e:
            raise ValueError('实验不存在')
        live = any(m['provider'] != 'mock' for m in e['config']['models'])
        if action == 'pause':
            c.execute("UPDATE experiments SET status='paused' WHERE id=%s", (eid,))
        elif action == 'resume':
            if live and (os.environ.get('ALLOW_PAID_API') != 'true' or authorization != '授权本实验付费调用'):
                raise ValueError('真实调用需要云端 ALLOW_PAID_API=true，并输入“授权本实验付费调用”')
            c.execute("UPDATE experiments SET status='queued',authorized_at=now() WHERE id=%s", (eid,))
        else:
            raise ValueError('未知操作')
        event(c, eid, action, {'live_api': live})


def retry_errors(eid, include_ambiguous=False, authorization=''):
    with connect() as c:
        e = c.execute('SELECT * FROM experiments WHERE id=%s FOR UPDATE', (eid,)).fetchone()
        if include_ambiguous and authorization != '接受重复计费风险':
            raise ValueError('请先核对供应商账单，再输入“接受重复计费风险”')
        states = ['failed', 'ambiguous'] if include_ambiguous else ['failed']
        n = c.execute("UPDATE tasks SET state='queued',available_at=now() WHERE experiment_id=%s AND state=ANY(%s)",
                      (eid, states)).rowcount
        c.execute("UPDATE experiments SET status='paused' WHERE id=%s", (eid,))
        event(c, eid, 'manual_retry', {'count': n, 'includes_ambiguous': include_ambiguous})
    return n


def update_budget(eid, budget):
    from decimal import Decimal
    budget = Decimal(str(budget))
    with connect() as c:
        e = c.execute('SELECT * FROM experiments WHERE id=%s FOR UPDATE', (eid,)).fetchone()
        if not budget.is_finite() or budget < e['spent'] + e['uncertain'] + e['reserved']:
            raise ValueError('新预算不能低于已记账、预留和待核对费用之和')
        c.execute('UPDATE experiments SET budget=%s WHERE id=%s', (budget, eid))
        event(c, eid, 'budget_changed', {'old': str(e['budget']), 'new': str(budget)})


def preview(eid, limit=100, after=0):
    return rows('''SELECT t.*, a.response,a.input_tokens,a.output_tokens,a.cost,a.error_code
                   FROM tasks t LEFT JOIN attempts a ON a.task_id=t.id AND a.number=t.attempts
                   WHERE t.experiment_id=%s AND t.id>%s ORDER BY t.id LIMIT %s''', (eid, after, limit))


def reconcile(eid, attempt_id, actual_cost, reason):
    from decimal import Decimal
    actual = Decimal(str(actual_cost))
    if not actual.is_finite() or actual < 0 or not reason.strip():
        raise ValueError('需填写实际费用和账单核对依据')
    with connect() as c:
        c.execute('SELECT id FROM experiments WHERE id=%s FOR UPDATE',(eid,))
        a = c.execute('''SELECT a.* FROM attempts a JOIN tasks t ON a.task_id=t.id
                       WHERE a.id=%s AND t.experiment_id=%s FOR UPDATE OF a''',(attempt_id,eid)).fetchone()
        if not a or a['cost'] is not None or a['status'] not in ('ambiguous','succeeded'):
            raise ValueError('该尝试不属于待核对费用，或已核对')
        c.execute('UPDATE attempts SET cost=%s WHERE id=%s',(actual,attempt_id))
        c.execute('''UPDATE experiments SET uncertain=uncertain-%s,spent=spent+%s,status='paused'
                    WHERE id=%s''',(a['reservation'],actual,eid))
        db_detail = {'attempt_id':attempt_id,'actual_cost':str(actual),'reason':reason[:500]}
        event(c,eid,'cost_reconciled',db_detail)
