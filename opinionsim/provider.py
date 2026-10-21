import hashlib
import json
import os
import httpx
from .domain import parse_answer
from .security import cipher, validate_endpoint


def perform(job):
    m, t, e = job['model'],job['task'],job['experiment']
    choices = e['config']['questions'][t['question_idx']]['choices'][t['language']]
    if m['provider'] == 'mock':
        key = hashlib.sha256((str(t['id'])+m['label']).encode()).digest()[0]
        answer = list(choices)[key % len(choices)]
        body = {'id':f'mock-{t["id"]}', 'model':m['model'],
                'choices':[{'message':{'content':json.dumps({'answer':answer})}}],
                'usage':{'prompt_tokens':100,'completion_tokens':10},'mock':True}
    else:
        if os.environ.get('ALLOW_PAID_API') != 'true' or e['authorized_at'] is None:
            return {'state':'failed','error_code':'paid_api_disabled'}
        try:
            cred = job['credential']
            endpoint = validate_endpoint(cred['base_url']) + '/chat/completions'
            secret = cipher().decrypt(cred['ciphertext'].encode()).decode()
        except Exception:
            return {'state':'failed','error_code':'credential_configuration_error'}
        try:
            # No SDK retries. Uncertain requests must never be replayed automatically.
            with httpx.Client(timeout=httpx.Timeout(90,connect=10),follow_redirects=False,trust_env=False) as client:
                with client.stream('POST',endpoint,headers={'Authorization':'Bearer '+secret},json=job['request']) as r:
                    if r.status_code == 429:
                        try:
                            retry = float(r.headers.get('retry-after','30'))
                        except ValueError:
                            retry = 30
                        return {'state':'retry','error_code':'http_429','retry_after':retry}
                    if r.status_code in (400,401,403,404,422):
                        return {'state':'failed','error_code':f'http_{r.status_code}'}
                    if r.status_code != 200:
                        return {'state':'ambiguous','error_code':f'http_{r.status_code}'}
                    chunks, n = [], 0
                    for chunk in r.iter_bytes():
                        n += len(chunk)
                        if n > 2_000_000:
                            return {'state':'ambiguous','error_code':'response_too_large'}
                        chunks.append(chunk)
                    body = json.loads(b''.join(chunks))
        except (httpx.HTTPError,ValueError):
            return {'state':'ambiguous','error_code':'transport_or_invalid_json'}
    try:
        raw = body['choices'][0]['message']['content']
        answer, error = parse_answer(raw,choices)
    except (KeyError,IndexError,TypeError,AttributeError):
        answer,error = None,'unexpected_response_schema'
    usage = body.get('usage') or {}
    inp,out = usage.get('prompt_tokens'),usage.get('completion_tokens')
    if not (type(inp) is int and inp >= 0 and type(out) is int and out >= 0):
        inp,out = None,None
    return {'state':'succeeded','response':body,'answer':answer,'parse_error':error,
            'input_tokens':inp,'output_tokens':out}
