import json
import os
from pathlib import Path
from .domain import PROMPTS,PROMPTS_ZH,read_csv,anonymize,sha
from .service import create_project,save_dataset,save_prompt,create_experiment

ROOT = Path(__file__).resolve().parents[1]


def default_config():
    return {'models':[{'label':f'Mock {i}','model':f'mock-{i}','provider':'mock',
                        'input_price':0,'output_price':0,'parameters':{}} for i in (1,2)],
            'languages':['zh','en'],'prompts':[{'name':name,'version':1,'body':PROMPTS_ZH[name],'body_en':body,
               'sha256':sha({'zh':PROMPTS_ZH[name],'en':body})} for name,body in PROMPTS],
            'questions':json.loads((ROOT/'examples/questions.json').read_text()),
            'repetitions':1,'max_output_tokens':512,'currency':'CNY',
            'expected_input_tokens':600,'expected_output_tokens':150,
            'methodology_note':'Synthetic example only. Replace questions and prompts after checking the paper.'}


def seed():
    pid = create_project('OpinionSim · 演示项目','全部为合成调查数据和模拟响应，不代表论文结果。')
    _,raw = read_csv((ROOT/'examples/survey.csv').read_bytes())
    records = anonymize(raw,{'age':'age','gender':'gender','education':'education','region':'region'},
                        {f'q{i}':f'q{i}' for i in range(1,7)},os.urandom(32))
    did = save_dataset(pid,'合成调查 · 3 人',records,{'synthetic':True,'rows':3,'sha256':sha(records)})
    for name,body in PROMPTS:
        save_prompt(pid,name,PROMPTS_ZH[name],body)
    eid = create_experiment(pid,did,'免费流程验证 · 288 个模拟任务',default_config(),0)
    return pid,eid


if __name__ == '__main__':
    from .db import init
    init()
    print(seed())
