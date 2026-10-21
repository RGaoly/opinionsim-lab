import json
from datetime import datetime,timezone
import httpx
from cryptography.fernet import Fernet
from opinionsim.provider import perform
from opinionsim.example import default_config


def job(monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setenv('FERNET_KEY',key.decode())
    monkeypatch.setenv('ALLOW_PAID_API','true')
    c = default_config()
    return {'model':{'provider':'compatible'},
            'task':{'id':1,'question_idx':0,'language':'en'},
            'experiment':{'config':c,'authorized_at':datetime.now(timezone.utc)},
            'request':{'model':'test-only','messages':[]},
            'credential':{'base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1',
                          'ciphertext':Fernet(key).encrypt(b'test-secret').decode()}}


def install_mock(monkeypatch,handler):
    client_class = httpx.Client
    monkeypatch.setattr('opinionsim.provider.httpx.Client',
                        lambda **kw:client_class(transport=httpx.MockTransport(handler),**kw))


def test_success_and_usage(monkeypatch):
    j = job(monkeypatch)
    def handler(req):
        assert req.headers['authorization']=='Bearer test-secret'
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"answer":"A"}'}}],
                                       'usage':{'prompt_tokens':35,'completion_tokens':4}})
    install_mock(monkeypatch,handler)
    r = perform(j)
    assert r['answer']=='A' and r['input_tokens']==35 and r['state']=='succeeded'


def test_timeout_and_5xx_do_not_auto_retry(monkeypatch):
    j = job(monkeypatch)
    calls = []
    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout('test-only')
    install_mock(monkeypatch,handler)
    assert perform(j)['state']=='ambiguous' and len(calls)==1


def test_429_is_only_safe_retry(monkeypatch):
    j = job(monkeypatch)
    install_mock(monkeypatch,lambda req:httpx.Response(429,headers={'retry-after':'40'}))
    r = perform(j)
    assert r['state']=='retry' and r['retry_after']==40


def test_unknown_usage_does_not_become_free(monkeypatch):
    j = job(monkeypatch)
    install_mock(monkeypatch,lambda req:httpx.Response(200,json={'choices':[{'message':{'content':'{"answer":"A"}'}}]}))
    r = perform(j)
    assert r['state']=='succeeded' and r['input_tokens'] is None and r['output_tokens'] is None
