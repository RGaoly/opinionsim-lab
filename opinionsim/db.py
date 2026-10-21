import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row


def connect():
    url = os.environ.get('DATABASE_URL', '')
    if not url:
        raise RuntimeError('请设置 DATABASE_URL；平台需要 PostgreSQL。')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=10)


def init():
    with connect() as c:
        c.execute('SELECT pg_advisory_xact_lock(73104422)')
        c.execute(Path(__file__).with_name('schema.sql').read_text())


def rows(sql, args=()):
    with connect() as c:
        return c.execute(sql, args).fetchall()


def event(c, eid, kind, detail=None):
    from psycopg.types.json import Jsonb
    c.execute('INSERT INTO events(experiment_id,kind,detail) VALUES (%s,%s,%s)',
              (eid, kind, Jsonb(detail or {})))


if __name__ == '__main__':
    init()
    print('Database schema ready')
