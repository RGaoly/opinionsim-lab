import argparse
import csv
import io
import json
from .db import connect


def safe_cell(value):
    value = '' if value is None else str(value)
    return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value


RESULT_SQL = '''SELECT t.id,t.rid,t.model_idx,t.language,t.prompt_idx,t.question_idx,t.repetition,
    t.state,t.attempts,t.answer,t.parse_error,p.truth,
    a.input_tokens,a.output_tokens,a.cost
    FROM tasks t JOIN experiments e ON e.id=t.experiment_id
    JOIN participants p ON p.dataset_id=e.dataset_id AND p.rid=t.rid
    LEFT JOIN attempts a ON a.task_id=t.id AND a.number=t.attempts
    WHERE t.experiment_id=%s AND t.id>%s ORDER BY t.id'''
RAW_SQL = '''SELECT a.*,t.rid,t.model_idx,t.language,t.prompt_idx,t.question_idx,t.repetition
    FROM attempts a JOIN tasks t ON t.id=a.task_id WHERE t.experiment_id=%s AND a.id>%s ORDER BY a.id'''


def write_export(eid, stream, fmt='jsonl', after=0, limit=None, raw=False):
    """Server-side cursor; no complete experiment loaded into web or worker RAM."""
    if raw and fmt != 'jsonl':
        raise ValueError('原始请求/响应及尝试记录使用 JSONL 导出')
    last,n = after,0
    with connect() as c:
        config = c.execute('SELECT config FROM experiments WHERE id=%s',(eid,)).fetchone()
        if not config:
            raise ValueError('实验不存在')
        with c.cursor(name='export') as cur:
            sql = RAW_SQL if raw else RESULT_SQL
            args = (eid,after)
            if limit is not None:
                sql += ' LIMIT %s'
                args += (limit,)
            cur.execute(sql,args)
            writer = None
            for row in cur:
                last,n = row['id'],n+1
                row['model_label'] = config['config']['models'][row['model_idx']]['label']
                row['prompt_version'] = config['config']['prompts'][row['prompt_idx']]['version']
                row['question_id'] = config['config']['questions'][row['question_idx']]['id']
                if fmt == 'csv':
                    row['truth'] = row['truth'].get(row['question_id'],'')
                    if writer is None:
                        writer = csv.DictWriter(stream,fieldnames=list(row))
                        writer.writeheader()
                    writer.writerow({k:safe_cell(v) for k,v in row.items()})
                else:
                    stream.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
    return n,last


def page_export(eid,fmt,after=0,raw=False):
    stream = io.StringIO()
    n,last = write_export(eid,stream,fmt,after=after,limit=500,raw=raw)
    return stream.getvalue().encode('utf-8-sig' if fmt=='csv' else 'utf-8'),n,last


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('experiment_id')
    parser.add_argument('--format',choices=['csv','jsonl'],default='jsonl')
    parser.add_argument('--raw',action='store_true')
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    with open(args.output,'w',encoding='utf-8-sig' if args.format=='csv' else 'utf-8',newline='') as f:
        n,_ = write_export(args.experiment_id,f,args.format,raw=args.raw)
    print(f'Exported {n} rows')
