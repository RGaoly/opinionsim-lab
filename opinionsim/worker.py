import logging
import os
import signal
import socket
import time
import uuid
from .db import init,connect
from .queue import claim,finish,recover_expired
from .provider import perform

log = logging.getLogger('opinionsim.worker')
stopping = False


def stop(*_):
    global stopping
    stopping = True


def step():
    recover_expired()
    job = claim()
    if not job:
        return False
    result = perform(job)
    finish(job,result)
    return True


def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    init()
    worker_id = socket.gethostname()+'-'+str(uuid.uuid4())[:8]
    log.info('Worker started; paid API enabled: %s',os.environ.get('ALLOW_PAID_API')=='true')
    while not stopping:
        try:
            with connect() as c:
                c.execute('''INSERT INTO workers(id,mode) VALUES (%s,%s) ON CONFLICT(id)
                          DO UPDATE SET heartbeat=now(),mode=excluded.mode''',
                          (worker_id,'paid_enabled' if os.environ.get('ALLOW_PAID_API')=='true' else 'mock_only'))
            if not step():
                time.sleep(2)
        except Exception as exc:
            # Never print URLs, secrets, prompts, payloads or exception messages.
            log.error('Worker operation failed (%s); inspect durable event log',type(exc).__name__)
            time.sleep(5)
    log.info('Worker stopped; unfinished requests require lease reconciliation')


if __name__ == '__main__':
    main()
