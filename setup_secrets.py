"""Create local .env without ever printing secrets or overwriting an existing file."""
import getpass
import os
import secrets
from pathlib import Path
from cryptography.fernet import Fernet
from opinionsim.security import hash_password

if __name__ == '__main__':
    target = Path('.env')
    if target.exists():
        raise SystemExit('.env 已存在；为避免丢失加密主密钥，不会覆盖。')
    password = getpass.getpass('设置至少 12 字符的研究室口令（不回显）：')
    if password != getpass.getpass('再次输入：'):
        raise SystemExit('两次口令不一致')
    encoded = hash_password(password)
    db_password = secrets.token_hex(24)
    content = '\n'.join([
        'POSTGRES_PASSWORD='+db_password,
        'DATABASE_URL=postgresql://opinionsim:'+db_password+'@db:5432/opinionsim',
        'APP_PASSWORD_HASH='+encoded,
        'FERNET_KEY='+Fernet.generate_key().decode(),
        'ALLOW_PAID_API=false',
        'API_ALLOWED_HOSTS=dashscope.aliyuncs.com,api.deepseek.com,api.openai.com',
        'DOMAIN=lab.example.org',''])
    fd = os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write(content)
    print('已创建权限为 600 的 .env。请安全备份；不要提交到 Git 或发到聊天中。')
