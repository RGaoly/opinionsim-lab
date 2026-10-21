"""Run against isolated schemas in TEST_DATABASE_URL, never against app tables."""
import io
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from urllib.parse import urlencode
import psycopg
import pytest
from cryptography.fernet import Fernet
from opinionsim import db,service,queue
from opinionsim.example import seed,default_config
from opinionsim.worker import step
from opinionsim.provider import perform
from opinionsim.domain import reserve_cost
from opinionsim.export import write_export


@pytest.fixture
def lab(monkeypatch):
    base = os.environ.get('TEST_DATABASE_URL')
    if not base:
        pytest.skip('Set TEST_DATABASE_URL for isolated PostgreSQL integration tests')
    schema = 'test_'+uuid.uuid4().hex
    with psycopg.connect(base) as c:
        c.execute(f'CREATE SCHEMA {schema}')
    from psycopg.conninfo import make_conninfo
    monkeypatch.setenv('DATABASE_URL',make_conninfo(base,options=f'-c search_path={schema}'))
    monkeypatch.setenv('FERNET_KEY',Fernet.generate_key().decode())
    monkeypatch.setenv('ALLOW_PAID_API','false')
    db.init()
    pid,eid = seed()
    yield pid,eid
    with psycopg.connect(base) as c:
        c.execute(f'DROP SCHEMA {schema} CASCADE')


def start(eid):
    service.control(eid,'resume')


def test_full_mock_run_exports_and_durable_reconnect(lab):
    _,eid = lab
    assert queue.claim() is None
    start(eid)
    count = 0
    while step():
        count += 1
    assert count==288
    e = db.rows('SELECT * FROM experiments WHERE id=%s',(eid,))[0]
    assert e['status']=='completed' and e['spent']==e['reserved']==e['uncertain']==0
    assert db.rows('SELECT count(*) AS n FROM attempts')[0]['n']==288
    s = io.StringIO()
    n,last = write_export(eid,s,'jsonl')
    assert n==288 and len(s.getvalue().splitlines())==288
    s = io.StringIO()
    assert write_export(eid,s,'jsonl',raw=True)[0]==288
    assert 'mock' in s.getvalue() and 'Authorization' not in s.getvalue()


def test_pause_and_resume_only_affect_new_claims(lab):
    _,eid = lab
    start(eid)
    job = queue.claim()
    service.control(eid,'pause')
    assert queue.claim() is None
    queue.finish(job,perform(job))
    assert db.rows('SELECT status FROM experiments')[0]['status']=='paused'
    start(eid)
    assert queue.claim() is not None


def test_budget_reserved_before_call_and_concurrent_claims(lab):
    _,eid = lab
    c = default_config()
    for model in c['models']:
        model.update(input_price=10,output_price=30)
    # Budget below a single maximum output reservation.
    with db.connect() as conn:
        from psycopg.types.json import Jsonb
        conn.execute('UPDATE experiments SET config=%s,budget=0.000001 WHERE id=%s',(Jsonb(c),eid))
    start(eid)
    assert queue.claim() is None
    assert db.rows('SELECT status FROM experiments')[0]['status']=='budget_blocked'
    service.update_budget(eid,0.06)
    start(eid)
    with ThreadPoolExecutor(max_workers=8) as executor:
        jobs = list(executor.map(lambda _:queue.claim(),range(8)))
    jobs = [j for j in jobs if j]
    assert len({j['task']['id'] for j in jobs})==len(jobs)
    e = db.rows('SELECT * FROM experiments')[0]
    assert 0 < e['reserved'] <= e['budget']
    assert e['reserved']==sum(j['task']['reservation'] for j in jobs)


def test_expired_requests_are_ambiguous_not_replayed(lab):
    _,eid = lab
    start(eid)
    job = queue.claim()
    with db.connect() as c:
        c.execute("UPDATE tasks SET lease_until=now()-interval '1 second' WHERE id=%s",(job['task']['id'],))
    queue.recover_expired()
    state = db.rows('SELECT state FROM tasks WHERE id=%s',(job['task']['id'],))[0]['state']
    assert state=='ambiguous'
    queue.finish(job,perform(job))
    assert db.rows('SELECT state FROM tasks WHERE id=%s',(job['task']['id'],))[0]['state']=='ambiguous'
    assert db.rows('SELECT response FROM attempts')[0]['response'] is not None
    with pytest.raises(ValueError):
        service.retry_errors(eid,True,'')
    service.retry_errors(eid,True,'接受重复计费风险')
    assert db.rows('SELECT status FROM experiments')[0]['status']=='paused'


def test_429_retries_and_attempt_history(lab):
    _,eid = lab
    start(eid)
    job = queue.claim()
    queue.finish(job,{'state':'retry','error_code':'http_429'})
    assert db.rows('SELECT state FROM tasks WHERE id=%s',(job['task']['id'],))[0]['state']=='retry'
    with db.connect() as c:
        c.execute('UPDATE tasks SET available_at=now() WHERE id=%s',(job['task']['id'],))
    second = queue.claim()
    assert second['task']['id']==job['task']['id'] and second['task']['attempts']==2
    queue.finish(second,perform(second))
    assert len(db.rows('SELECT * FROM attempts WHERE task_id=%s',(job['task']['id'],)))==2


def test_real_api_requires_server_flag_and_typed_authorization(lab,monkeypatch):
    _,eid = lab
    c = default_config()
    for m in c['models']:
        m['provider']='compatible'
    with db.connect() as conn:
        from psycopg.types.json import Jsonb
        conn.execute('UPDATE experiments SET config=%s WHERE id=%s',(Jsonb(c),eid))
    with pytest.raises(ValueError):
        service.control(eid,'resume','授权本实验付费调用')
    monkeypatch.setenv('ALLOW_PAID_API','true')
    with pytest.raises(ValueError):
        service.control(eid,'resume','')
    service.control(eid,'resume','授权本实验付费调用')
    monkeypatch.setenv('ALLOW_PAID_API','false')
    assert queue.claim() is None


def test_credentials_encrypted_and_not_returned_in_exports(lab):
    service.save_credential('Test','https://dashscope.aliyuncs.com/compatible-mode/v1','never-export-this-secret',30)
    record = db.rows('SELECT * FROM credentials')[0]
    assert 'never-export' not in record['ciphertext']
    from opinionsim.security import cipher
    assert cipher().decrypt(record['ciphertext'].encode()).decode()=='never-export-this-secret'


def test_manual_reconciliation_is_once_only(lab):
    _,eid = lab
    start(eid)
    job = queue.claim()
    # Emulate a charged uncertain request without ever contacting a provider.
    with db.connect() as c:
        c.execute('UPDATE tasks SET reservation=0.1 WHERE id=%s',(job['task']['id'],))
        c.execute('UPDATE attempts SET reservation=0.1 WHERE claim_token=%s',(job['task']['claim_token'],))
        c.execute('UPDATE experiments SET reserved=0.1')
    job['task']['reservation']=Decimal('0.1')
    queue.finish(job,{'state':'ambiguous','error_code':'network_timeout'})
    e = db.rows('SELECT * FROM experiments')[0]
    assert e['uncertain']==Decimal('0.1') and e['reserved']==0
    aid = db.rows('SELECT id FROM attempts')[0]['id']
    service.reconcile(eid,aid,0.04,'provider invoice test fixture')
    e = db.rows('SELECT * FROM experiments')[0]
    assert e['uncertain']==0 and e['spent']==Decimal('0.04') and e['status']=='paused'
    with pytest.raises(ValueError):
        service.reconcile(eid,aid,0.04,'duplicate')


def test_experiment_creation_idempotent_and_snapshot(lab):
    pid,eid = lab
    e = db.rows('SELECT * FROM experiments')[0]
    assert service.create_experiment(pid,e['dataset_id'],'same',e['config'],0,eid)==eid
    service.save_prompt(pid,'direct','{profile} {question} {choices} new version')
    assert db.rows('SELECT config FROM experiments')[0]['config']==e['config']


def test_materialize_192000_tasks_without_provider_calls(lab):
    pid,_ = lab
    records = [{'rid':f'synthetic-{i:05d}','profile':{'age_band':'20–29'},'truth':{}} for i in range(2000)]
    did = service.save_dataset(pid,'Synthetic scale test',records,{'synthetic':True,'rows':2000})
    eid = service.create_experiment(pid,did,'192000 queue only',default_config(),0)
    assert db.rows('SELECT count(*) AS n FROM tasks WHERE experiment_id=%s',(eid,))[0]['n']==192000
    assert db.rows('SELECT count(*) AS n FROM attempts a JOIN tasks t ON t.id=a.task_id WHERE t.experiment_id=%s',(eid,))[0]['n']==0
    assert db.rows('SELECT status FROM experiments WHERE id=%s',(eid,))[0]['status']=='draft'
