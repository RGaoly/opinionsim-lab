import os
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from opinionsim.security import hash_password
from test_postgres import lab


def test_authenticated_pages_and_mock_controls(lab,monkeypatch):
    monkeypatch.setenv('APP_PASSWORD_HASH',hash_password('test-lab-password-123'))
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30)
    at.session_state['authenticated']=True
    at.run()
    assert not at.exception
    for page in ['调查数据','模型与密钥','提示语版本','配置实验','运行监控','结果与导出','上线与方法']:
        at.radio[0].set_value(page).run()
        assert not at.exception, (page,[str(e) for e in at.exception])
        assert not at.error, (page,[e.value for e in at.error])


def test_password_login_required(lab,monkeypatch):
    monkeypatch.setenv('APP_PASSWORD_HASH',hash_password('test-lab-password-123'))
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
    assert not at.exception
    assert at.text_input[0].label=='研究室口令'
    at.text_input[0].set_value('test-lab-password-123')
    at.button[0].click().run()
    assert not at.exception
    assert len(at.radio)==1
