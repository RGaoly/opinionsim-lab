import base64
import hashlib
import hmac
import os
from urllib.parse import urlsplit
from cryptography.fernet import Fernet


def hash_password(password, salt=None):
    if len(password) < 12:
        raise ValueError('登录口令至少 12 个字符')
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600_000)
    return salt + ':' + base64.b64encode(digest).decode()


def verify_password(password, encoded):
    try:
        salt, _ = encoded.split(':', 1)
        return hmac.compare_digest(hash_password(password, salt), encoded)
    except (ValueError, TypeError):
        return False


def cipher():
    key = os.environ.get('FERNET_KEY', '')
    if not key:
        raise ValueError('尚未设置 FERNET_KEY；密钥必须独立于数据库保存')
    return Fernet(key.encode())


def validate_endpoint(url):
    parsed = urlsplit(url)
    allowed = {h.strip() for h in os.environ.get(
        'API_ALLOWED_HOSTS', 'dashscope.aliyuncs.com,api.deepseek.com,api.openai.com').split(',')}
    if (parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
        raise ValueError('只允许管理员 API_ALLOWED_HOSTS 中的 HTTPS API 地址')
    return url.rstrip('/')
