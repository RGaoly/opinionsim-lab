"""Bounded, in-memory synthetic walkthrough. No database, credentials or network."""
import copy
import csv
import hashlib
import io
import itertools
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .domain import PROMPTS, PROMPTS_ZH, anonymize, canonical, price, read_csv, render, sha

ROOT = Path(__file__).resolve().parents[1]
MAX_DEMO_PEOPLE = 3
MAX_DEMO_TASKS = 288


def config():
    return {'models':[{'label':f'Mock {i}', 'model':f'mock-{i}', 'provider':'mock',
                       'input_price':1.0,'output_price':3.0,'parameters':{}} for i in (1,2)],
            'languages':['zh','en'],
            'prompts':[{'name':n,'version':1,'body':PROMPTS_ZH[n],'body_en':b,
                        'sha256':sha({'zh':PROMPTS_ZH[n],'en':b})} for n,b in PROMPTS],
            'questions':json.loads((ROOT/'examples/questions.json').read_text()),
            'repetitions':1,'max_output_tokens':512,'currency':'CNY',
            'expected_input_tokens':600,'expected_output_tokens':150,
            'methodology_note':'Synthetic demonstration; no paid API or background execution.'}


def sample_people():
    _,records = read_csv((ROOT/'examples/survey.csv').read_bytes())
    return anonymize(records,{'age':'age','gender':'gender','education':'education','region':'region'},
                     {f'q{i}':f'q{i}' for i in range(1,7)},b'opinionsim-public-synthetic-example')


def event(exp, kind, detail=''):
    exp['events'].append({'time':datetime.now(timezone.utc).isoformat(),'kind':kind,'detail':detail,'mock':True})


def make_experiment(name, cfg, people, project_id, planned_people=None, fail_once=False):
    cfg = copy.deepcopy(cfg)
    bounded = copy.deepcopy(people[:MAX_DEMO_PEOPLE])
    if not bounded:
        raise ValueError('需要至少一名合成受访者')
    tasks = []
    # Repetitions and large populations affect estimates only. This walkthrough
    # materializes at most 288 synthetic tasks and never sends HTTP requests.
    for person in bounded:
        for m,lang,p,q in itertools.product(range(2),['zh','en'],range(4),range(6)):
            tasks.append({'id':len(tasks)+1,'rid':person['rid'],'model_idx':m,'language':lang,
                          'prompt_idx':p,'question_idx':q,'repetition':0,'state':'queued',
                          'answer':None,'attempts':[],'profile':person['profile'],
                          'truth':person['truth'].get(cfg['questions'][q]['id']), 'mock':True})
    exp = {'id':str(uuid.uuid4()),'name':name,'project_id':project_id,'config':cfg,
           'config_sha256':sha(cfg),'state':'draft','tasks':tasks,'events':[],
           'planned_people':planned_people or len(people),
           'planned_calls':(planned_people or len(people))*96*cfg['repetitions'],
           'fail_once':fail_once,'failure_injected':False,'actual_cost':0}
    event(exp,'created',f'{len(tasks)} bounded mock tasks')
    return exp


def workspace():
    pid = str(uuid.uuid4())
    cfg = config()
    people = sample_people()
    exp = make_experiment('已完成的合成示例 · 288 条',cfg,people,pid)
    resume(exp)
    advance(exp,MAX_DEMO_TASKS)
    return {'projects':[{'id':pid,'name':'我的民意模拟研究','notes':'合成示例，不代表论文结论。'}],
            'datasets':[{'id':str(uuid.uuid4()),'project_id':pid,'name':'合成调查 · 3 人','people':people}],
            'prompts':{pid:copy.deepcopy(cfg['prompts'])},'experiments':[exp]}


def resume(exp):
    exp['state']='queued'
    event(exp,'resume','模拟恢复；没有启动云端 Worker')


def pause(exp):
    exp['state']='paused'
    event(exp,'pause','模拟暂停')


def advance(exp,batch=48):
    if exp['state'] not in ('queued','running'):
        return 0
    count = 0
    for task in exp['tasks']:
        if task['state']!='queued':
            continue
        if count>=min(batch,MAX_DEMO_TASKS):
            break
        count+=1
        prompt = render(exp['config'],task,task['profile'])
        number = len(task['attempts'])+1
        if exp['fail_once'] and task['id']==7 and not exp['failure_injected']:
            exp['failure_injected']=True
            task['state']='failed'
            task['attempts'].append({'number':number,'request':prompt,'response':None,
                                     'error_code':'simulated_429','mock':True,'actual_cost':0})
            event(exp,'simulated_failure','任务 7：供体验重试流程')
            continue
        codes = list(exp['config']['questions'][task['question_idx']]['choices'][task['language']])
        digest = hashlib.sha256((prompt+str(task['model_idx'])).encode()).digest()
        answer = codes[digest[0]%len(codes)]
        raw = {'id':f'mock-{task["id"]}-{number}','model':exp['config']['models'][task['model_idx']]['model'],
               'choices':[{'message':{'content':json.dumps({'answer':answer,'mock':True})}}],
               'usage':{'prompt_tokens':len(prompt.encode())//3,'completion_tokens':16},'mock':True}
        task['state']='succeeded'
        task['answer']=answer
        task['attempts'].append({'number':number,'request':prompt,'response':raw,
                                 'error_code':None,'mock':True,'actual_cost':0})
    pending = any(t['state']=='queued' for t in exp['tasks'])
    failed = any(t['state']=='failed' for t in exp['tasks'])
    exp['state']='running' if pending else ('completed_errors' if failed else 'completed')
    event(exp,'advance',f'本次模拟处理 {count} 条')
    return count


def retry(exp):
    count = 0
    for task in exp['tasks']:
        if task['state']=='failed':
            task['state']='queued'
            count+=1
    exp['state']='paused'
    event(exp,'retry',f'{count} 条模拟失败项重新排队，等待恢复')
    return count


def estimate(cfg, people):
    per_model = people*48*cfg['repetitions']
    return sum(price(m,cfg['expected_input_tokens'],cfg['expected_output_tokens'])*per_model for m in cfg['models'])


def result_rows(exp):
    out=[]
    for task in exp['tasks']:
        out.append({'task_id':task['id'],'rid':task['rid'],
                    'model':exp['config']['models'][task['model_idx']]['label'],
                    'language':task['language'],
                    'prompt':exp['config']['prompts'][task['prompt_idx']]['name'],
                    'prompt_version':exp['config']['prompts'][task['prompt_idx']]['version'],
                    'question':exp['config']['questions'][task['question_idx']]['id'],
                    'state':task['state'],'answer':task['answer'],'truth':task['truth'],
                    'attempts':len(task['attempts']),'mock':True,'actual_cost':0})
    return out


def export(exp,fmt='jsonl',raw=False):
    if raw:
        return '\n'.join(json.dumps({'task_id':t['id'],'mock':True,**a},ensure_ascii=False)
                         for t in exp['tasks'] for a in t['attempts'])+'\n'
    data = result_rows(exp)
    if fmt=='csv':
        s=io.StringIO()
        writer=csv.DictWriter(s,fieldnames=list(data[0]))
        writer.writeheader()
        for row in data:
            # Guard spreadsheet formulas in user-edited labels.
            writer.writerow({k:("'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v)
                             for k,v in row.items()})
        return s.getvalue()
    return '\n'.join(json.dumps(row,ensure_ascii=False) for row in data)+'\n'
