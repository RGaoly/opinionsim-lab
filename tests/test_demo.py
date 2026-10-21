import copy
import csv
import io
import json
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from opinionsim import demo

ENTRY = str(Path(__file__).resolve().parents[1]/'streamlit_app.py')


def button(at,label):
    return next(b for b in at.button if b.label==label)


def test_demo_workspace_is_bounded_and_isolated():
    one,two=demo.workspace(),demo.workspace()
    assert one['experiments'][0]['state']=='completed'
    assert len(one['experiments'][0]['tasks'])==288
    one['projects'][0]['notes']='edited'
    assert two['projects'][0]['notes']!='edited'
    cfg=demo.config()
    cfg['repetitions']=100
    exp=demo.make_experiment('scale estimate',cfg,demo.sample_people()*1000,'test',2000)
    assert exp['planned_calls']==19_200_000
    assert len(exp['tasks'])==288 and not any(t['attempts'] for t in exp['tasks'])
    cfg['prompts'][0]['body']='changed'
    assert exp['config']['prompts'][0]['body']!='changed'


def test_simulated_pause_retry_and_exports():
    exp=demo.make_experiment('demo',demo.config(),demo.sample_people(),'test',fail_once=True)
    assert demo.advance(exp)==0
    demo.resume(exp)
    demo.advance(exp,48)
    assert sum(t['state']=='succeeded' for t in exp['tasks'])==47
    demo.pause(exp)
    assert demo.advance(exp,288)==0
    demo.resume(exp)
    demo.advance(exp,288)
    assert exp['state']=='completed_errors'
    assert demo.retry(exp)==1 and exp['state']=='paused'
    demo.resume(exp)
    demo.advance(exp,288)
    assert exp['state']=='completed' and exp['actual_cost']==0
    assert len(exp['tasks'][6]['attempts'])==2
    rows=list(csv.DictReader(io.StringIO(demo.export(exp,'csv'))))
    assert len(rows)==288 and all(r['mock']=='True' for r in rows)
    records=[json.loads(x) for x in demo.export(exp).splitlines()]
    assert len(records)==288 and all(r['mock'] and r['actual_cost']==0 for r in records)
    assert len(demo.export(exp,raw=True).splitlines())==289


@pytest.fixture
def no_backend(monkeypatch):
    for key in ['DATABASE_URL','FERNET_KEY','APP_PASSWORD_HASH','ALLOW_PAID_API']:
        monkeypatch.delenv(key,raising=False)
    def forbidden(*args,**kwargs):
        raise AssertionError('The public demo must not connect to any backend')
    monkeypatch.setattr('psycopg.connect',forbidden)
    monkeypatch.setattr('httpx.Client.send',forbidden)
    monkeypatch.setattr('httpx.AsyncClient.send',forbidden)


def test_public_pages_without_secrets_database_or_api(no_backend):
    at=AppTest.from_file(ENTRY,default_timeout=30).run()
    assert not at.exception and not at.error
    for page in ['调查数据','模型与密钥','提示语版本','配置实验','运行监控','结果与导出','上线与方法']:
        at.radio[0].set_value(page).run()
        assert not at.exception,(page,[str(x) for x in at.exception])
        assert not at.error,(page,[x.value for x in at.error])
        if page=='模型与密钥':
            assert len(at.text_input)==0


def test_public_project_creation_and_two_sessions(no_backend):
    one=AppTest.from_file(ENTRY,default_timeout=30).run()
    two=AppTest.from_file(ENTRY,default_timeout=30).run()
    one.text_input[0].set_value('独立的测试项目')
    button(one,'创建项目').click().run()
    assert not one.exception
    assert len(one.session_state.lab_demo['projects'])==2
    assert len(two.session_state.lab_demo['projects'])==1


def test_public_configure_monitor_and_retry(no_backend):
    at=AppTest.from_file(ENTRY,default_timeout=30).run()
    at.radio[0].set_value('配置实验').run()
    assert any(m.value=='192,000' for m in at.metric)
    button(at,'创建模拟实验草稿').click().run()
    assert not at.exception and not at.error
    exp=at.session_state.lab_demo['experiments'][-1]
    assert exp['planned_calls']==192000 and len(exp['tasks'])==288
    at.radio[0].set_value('运行监控').run()
    button(at,'模拟排队 / 恢复').click().run()
    button(at,'模拟推进 48 条').click().run()
    button(at,'模拟暂停').click().run()
    assert button(at,'模拟推进 48 条').disabled
    button(at,'模拟排队 / 恢复').click().run()
    button(at,'完成本轮模拟').click().run()
    assert exp['state']=='completed_errors'
    button(at,'重新排队模拟失败项').click().run()
    button(at,'模拟排队 / 恢复').click().run()
    button(at,'完成本轮模拟').click().run()
    assert not at.exception and exp['state']=='completed'
