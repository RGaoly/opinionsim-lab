import hmac
import io
import json
import os
import time
import uuid
from decimal import Decimal
from pathlib import Path
import pandas as pd
import streamlit as st
from opinionsim import db,service
from opinionsim.domain import PROFILE_FIELDS,PROMPTS,PROMPTS_ZH,read_csv,anonymize,sha,price,validate_config
from opinionsim.security import verify_password
from opinionsim.example import default_config,seed
from opinionsim.export import page_export

st.set_page_config(page_title='OpinionSim Lab',page_icon='◉',layout='wide')
st.markdown('''<style>
 .stApp {background:#f5f7fa;} h1,h2,h3 {color:#14283d;letter-spacing:-.03em;}
 [data-testid="stSidebar"] {background:#13283c;color:#e6edf4;}
 [data-testid="stSidebar"] * {color:inherit;}
 [data-testid="stMetric"] {background:white;border:1px solid #e2e8ef;border-radius:12px;padding:18px;}
 .block-container {padding-top:2rem;max-width:1440px;} div.stButton>button[kind="primary"] {background:#007f78;border:0;}
 </style>''',unsafe_allow_html=True)


def login():
    if st.session_state.get('authenticated'):
        return
    encoded = os.environ.get('APP_PASSWORD_HASH','')
    if not encoded:
        st.error('平台尚未设置登录口令。请按上线指南生成 APP_PASSWORD_HASH 后启动。')
        st.stop()
    st.title('◉ OpinionSim Lab')
    st.caption('研究工作台 · 项目、实验与证据，都留在云端')
    with st.form('login'):
        password = st.text_input('研究室口令',type='password')
        submitted = st.form_submit_button('进入研究室',type='primary')
    if submitted:
        # Password is salted PBKDF2. Add identity proxy for public multi-user access.
        time.sleep(1)
        if verify_password(password,encoded):
            st.session_state.authenticated = True
            st.rerun()
        st.error('口令不正确')
    st.stop()


login()
try:
    db.init()
except Exception:
    st.error('数据库连接失败。请检查云端 DATABASE_URL、私网连接和数据库状态。')
    st.stop()

with st.sidebar:
    st.title('◉ OpinionSim')
    st.caption('RESEARCH LAB / 研究工作台')
    section = st.radio('工作区',['项目总览','调查数据','模型与密钥','提示语版本','配置实验','运行监控','结果与导出','上线与方法'])
    projects = db.rows('SELECT * FROM projects ORDER BY created_at DESC')
    pid = st.selectbox('当前项目',[str(p['id']) for p in projects],
                       format_func=lambda v:next(p['name'] for p in projects if str(p['id'])==v)) if projects else None
    st.divider()
    st.caption('页面可以关闭；云端 Worker 独立执行。\n\n默认仅模拟模式，真实调用需单独授权。')
    if st.button('退出登录'):
        st.session_state.clear()
        st.rerun()

st.caption('OPINIONSIM LAB / 大语言模型模拟民意实验')
st.title(section)


def experiments():
    if not pid:
        return []
    return db.rows('SELECT * FROM experiments WHERE project_id=%s ORDER BY created_at DESC',(pid,))


def pick_experiment():
    values = experiments()
    if not values:
        st.info('先创建一个实验。演示项目内含可免费运行的模拟实验。')
        st.stop()
    eid = st.selectbox('选择实验',[str(e['id']) for e in values],
                        format_func=lambda v:next(e['name'] for e in values if str(e['id'])==v))
    return next(e for e in values if str(e['id'])==eid)


try:
    if section == '项目总览':
        st.write('将调查、提示语、模型配置和每次响应保存在同一个可追溯的研究项目中。')
        cols = st.columns(3)
        cols[0].metric('研究项目',len(projects))
        cols[1].metric('当前项目实验',len(experiments()))
        cols[2].metric('计费模式','允许授权' if os.environ.get('ALLOW_PAID_API')=='true' else '仅模拟')
        left,right = st.columns([1.4,1])
        with left:
            with st.form('project'):
                name = st.text_input('新项目名称')
                notes = st.text_area('研究说明 / 过程记录')
                if st.form_submit_button('创建项目',type='primary'):
                    service.create_project(name,notes)
                    st.rerun()
            if pid:
                project = next(p for p in projects if str(p['id'])==pid)
                st.subheader(project['name'])
                st.write(project['notes'] or '暂无项目记录')
                with st.form('project_notes'):
                    updated = st.text_area('更新项目记录',project['notes'])
                    if st.form_submit_button('保存记录'):
                        with db.connect() as c:
                            c.execute('UPDATE projects SET notes=%s WHERE id=%s',(updated,pid))
                            db.event(c,None,'project_notes_updated',{'project_id':pid})
                        st.rerun()
        with right:
            st.subheader('从 0 到第一个实验')
            st.write('① 建项目和数据集\n\n② 保存四种提示语\n\n③ 配置 96 个实验条件\n\n④ 核准预算后排队\n\n⑤ 检查并导出结果')
            if st.button('创建免费演示项目'):
                seed()
                st.rerun()
            st.caption('演示含 3 名合成受访者、288 个模拟任务；不会访问任何模型服务。')
    elif section == '调查数据':
        if not pid:
            st.info('请先创建项目。')
            st.stop()
        st.info('原 CSV 仅在本次上传内存中处理。数据库只保存选定的分组画像、随机受访者编号和单独存放的真实答案；真实答案不会进入模型提示。')
        st.caption('去标识化不等于不可重识别。请去除姓名、联系方式、精确地址和自由文本，检查小样本组合后再保存。')
        upload = st.file_uploader('调查数据 CSV（UTF-8，20 MB / 10,000 人以内）',type=['csv'])
        if upload:
            fields,records = read_csv(upload.getvalue())
            st.write(f'{len(records):,} 行 · {len(fields)} 列；未展示原始数据')
            dataset_name = st.text_input('数据集名称',upload.name)
            chosen = st.multiselect('允许发给模型的画像字段（将列映射到标准字段）',sorted(PROFILE_FIELDS),default=['age','gender','education','region'])
            mapping = {}
            for target in chosen:
                mapping[target] = st.selectbox(target,fields,index=fields.index(target) if target in fields else 0,key='map_'+target)
            truth = {}
            with st.expander('真实答案列：仅用于后续统计，不进入提示语',expanded=True):
                for i in range(1,7):
                    qid = f'q{i}'
                    col = st.selectbox(qid,['不提供']+fields,index=fields.index(qid)+1 if qid in fields else 0,key='truth_'+qid)
                    if col != '不提供':
                        truth[qid] = col
            cleaned = anonymize(records,mapping,truth,os.urandom(32))
            st.subheader('去标识化预览')
            st.dataframe(pd.DataFrame([{'rid':r['rid'],**r['profile']} for r in cleaned[:10]]),hide_index=True)
            confirmed = st.checkbox('我已检查画像与真实答案，确认可以按研究授权保存和发送所选画像')
            if st.button('保存数据集',disabled=not confirmed,type='primary'):
                service.save_dataset(pid,dataset_name,cleaned,{'rows':len(cleaned),'profile_fields':chosen,
                                     'truth_fields':list(truth),'sha256':sha(cleaned),'deidentification':'whitelist, age decade bins, random HMAC IDs'})
                st.success('数据集已持久保存；原 CSV 未存盘。')
        st.dataframe(pd.DataFrame(db.rows('SELECT id,name,manifest,created_at FROM datasets WHERE project_id=%s ORDER BY created_at DESC',(pid,))),hide_index=True)
    elif section == '模型与密钥':
        st.write('API Key 加密后保存到数据库。加密主密钥只在云端环境变量中保存，页面不会回显已保存的 Key。')
        with st.form('credential',clear_on_submit=True):
            label = st.text_input('凭据名称，例如 百炼-北京-研究')
            url = st.text_input('兼容 API Base URL','https://dashscope.aliyuncs.com/compatible-mode/v1')
            secret = st.text_input('API Key',type='password')
            rpm = st.number_input('该凭据每分钟最多请求数',min_value=1,max_value=600,value=30)
            if st.form_submit_button('加密保存 / 更新凭据',type='primary'):
                service.save_credential(label,url,secret,int(rpm))
                st.success('凭据已加密保存')
        creds = db.rows('SELECT id,label,base_url,rpm,active,created_at FROM credentials ORDER BY label')
        st.dataframe(pd.DataFrame(creds),hide_index=True)
        if creds:
            cid = st.selectbox('停用凭据',[str(c['id']) for c in creds],format_func=lambda v:next(c['label'] for c in creds if str(c['id'])==v))
            if st.button('停用所选凭据'):
                with db.connect() as c:
                    c.execute('UPDATE credentials SET active=false WHERE id=%s',(cid,))
                    db.event(c,None,'credential_disabled',{'credential_id':cid})
                st.rerun()
        st.caption('支持 Chat Completions 兼容接口；供应商原生 Batch、原生 Claude / Azure 部署接口尚未接入。请使用你有资格访问的服务。')
    elif section == '提示语版本':
        if not pid:
            st.info('请先创建项目。')
            st.stop()
        st.warning('内置四种提示语是流程示例，尚未核对论文原文。正式复现前请替换为原文及经核对的中英文版本。')
        st.caption('变量：{profile} {question} {choices} {language}。JSON 中的字面花括号须双写。每次保存新增版本，不覆盖历史版本。')
        template = st.selectbox('示例起点',[n for n,_ in PROMPTS])
        with st.form('prompt'):
            pname = st.text_input('提示语名称',template)
            body = st.text_area('中文提示语模板',PROMPTS_ZH[template],height=180)
            body_en = st.text_area('英文提示语模板',dict(PROMPTS)[template],height=180)
            if st.form_submit_button('保存新版本',type='primary'):
                service.save_prompt(pid,pname,body,body_en)
                st.success('新版本已保存')
        if st.button('为当前项目添加四种示例提示语'):
            for n,b in PROMPTS:
                service.save_prompt(pid,n,PROMPTS_ZH[n],b)
            st.rerun()
        st.dataframe(pd.DataFrame(db.rows('SELECT name,version,sha256,body,created_at FROM prompts WHERE project_id=%s ORDER BY name,version DESC',(pid,))),hide_index=True)
    elif section == '配置实验':
        if not pid:
            st.info('请先创建项目。')
            st.stop()
        datasets = db.rows('SELECT d.*,count(p.rid) AS n FROM datasets d JOIN participants p ON p.dataset_id=d.id WHERE d.project_id=%s GROUP BY d.id',(pid,))
        prompts = db.rows('SELECT * FROM prompts WHERE project_id=%s ORDER BY name,version DESC',(pid,))
        if not datasets or not prompts:
            st.info('需要至少一个数据集及四种提示语版本。')
            st.stop()
        did = st.selectbox('数据集',[str(d['id']) for d in datasets],format_func=lambda v:next(d['name'] for d in datasets if str(d['id'])==v))
        selected = st.multiselect('精确选择四种提示语版本',[str(p['id']) for p in prompts],max_selections=4,
                                 format_func=lambda v:next(f'{p["name"]} / v{p["version"]}' for p in prompts if str(p['id'])==v))
        name = st.text_input('实验名称','2 × 2 × 4 × 6 因子实验')
        mock = st.toggle('免费模拟模式',value=True)
        currency = st.selectbox('所有模型价格的统一币种',['CNY','USD'])
        creds = db.rows('SELECT id,label FROM credentials WHERE active ORDER BY label')
        models = []
        cols = st.columns(2)
        for idx,col in enumerate(cols):
            with col:
                st.subheader(f'模型 {idx+1}')
                label = st.text_input('模型标签',f'Model {idx+1}',key=f'mlabel{idx}')
                model = st.text_input('供应商模型 ID / 固定版本',f'mock-{idx+1}' if mock else '',key=f'mid{idx}')
                cid = None
                if not mock:
                    cid = st.selectbox('API 凭据',[str(c['id']) for c in creds],key=f'cid{idx}',format_func=lambda v:next(c['label'] for c in creds if str(c['id'])==v)) if creds else None
                inp = st.number_input('每百万输入 Token 原价',min_value=0.0,value=0.0 if mock else 1.0,key=f'inp{idx}')
                out = st.number_input('每百万输出 Token 原价',min_value=0.0,value=0.0 if mock else 3.0,key=f'out{idx}')
                params = st.text_input('模型参数 JSON','{}',key=f'params{idx}')
                models.append({'label':label,'model':model,'provider':'mock' if mock else 'compatible',
                               'credential_id':cid,'input_price':inp,'output_price':out,'parameters':json.loads(params)})
        question_text = st.text_area('六道中英文问题及选项 JSON',json.dumps(default_config()['questions'],ensure_ascii=False,indent=2),height=200)
        rep = st.number_input('每位受访者 / 每条件重复次数',min_value=1,max_value=100,value=1)
        output_max = st.number_input('单次输出 Token 硬上限（需供应商支持 max_tokens）',min_value=16,max_value=8192,value=512)
        expected_in = st.number_input('平均输入 Token 估计',min_value=1,value=600)
        expected_out = st.number_input('平均输出 Token 估计',min_value=1,max_value=int(output_max),value=min(150,int(output_max)))
        budget = st.number_input('本实验 API 费用上限（不扣除尚未核实的券或额度）',min_value=0.0,value=0.0 if mock else 10.0)
        note = st.text_area('预注册 / 论文方法核对记录','待核对原文：样本、题目、提示语、模型版本、温度、思考模式、重复次数与指标聚合口径。')
        n = next(d['n'] for d in datasets if str(d['id'])==did)
        total = n*96*int(rep)
        estimate = sum(price(m,int(expected_in),int(expected_out))*Decimal(total//2) for m in models)
        a,b,c = st.columns(3)
        a.metric('计划 API 请求',f'{total:,}')
        b.metric('预估原价',f'{estimate:.4f} {currency}')
        c.metric('实验条件','96')
        st.caption('2,000 人 × 96 条件 × 1 次 = 192,000 请求。运行前每次按输入字节保守估算与最大输出预留预算；实际账单仍以供应商为准。')
        if 'submission_id' not in st.session_state:
            st.session_state.submission_id = str(uuid.uuid4())
        if st.button('生成持久任务草稿',type='primary',disabled=len(selected)!=4):
            config = {'models':models,'languages':['zh','en'],
                      'prompts':[{k:p[k] for k in ('name','version','body','body_en','sha256')} for ident in selected for p in prompts if str(p['id'])==ident],
                      'questions':json.loads(question_text),'repetitions':int(rep),'max_output_tokens':int(output_max),
                      'currency':currency,'expected_input_tokens':int(expected_in),'expected_output_tokens':int(expected_out),'methodology_note':note}
            with st.spinner('持久保存配置快照和任务队列…'):
                eid = service.create_experiment(pid,did,name,config,budget,st.session_state.submission_id)
            st.session_state.submission_id = str(uuid.uuid4())
            st.success(f'实验草稿已生成：{eid}。到运行监控页面核准后排队。')
    elif section == '运行监控':
        e = pick_experiment()
        eid = str(e['id'])
        if st.button('刷新状态'):
            st.rerun()
        counts = db.rows('SELECT state,count(*) AS n FROM tasks WHERE experiment_id=%s GROUP BY state',(eid,))
        by_state = {r['state']:r['n'] for r in counts}
        done = sum(by_state.get(s,0) for s in ['succeeded','failed','ambiguous'])
        st.progress(done/e['total'],text=f'{done:,} / {e["total"]:,} 已终结 · 状态 {e["status"]}')
        a,b,c,d = st.columns(4)
        a.metric('成功请求',f'{by_state.get("succeeded",0):,}')
        b.metric('已知费用',f'{e["spent"]:.4f} {e["currency"]}')
        c.metric('进行中预留',f'{e["reserved"]:.4f}')
        d.metric('待核对费用',f'{e["uncertain"]:.4f}')
        st.write('预算上限：',str(e['budget']),e['currency'])
        st.dataframe(pd.DataFrame(counts),hide_index=True)
        st.caption('暂停立即阻止后续领取；已经发出的请求仍会完成并记账。超时或 Worker 崩溃后的请求不自动重发，以免重复计费。')
        live = any(m['provider']!='mock' for m in e['config']['models'])
        auth = st.text_input('真实调用授权：输入“授权本实验付费调用”') if live else ''
        a,b = st.columns(2)
        if a.button('排队 / 恢复',type='primary'):
            service.control(eid,'resume',auth)
            st.rerun()
        if b.button('暂停后续请求'):
            service.control(eid,'pause')
            st.rerun()
        with st.expander('预算调整与失败重试'):
            new_budget = st.number_input('新预算',min_value=0.0,value=float(e['budget']))
            if st.button('保存预算（不会自动恢复）'):
                service.update_budget(eid,new_budget)
                st.rerun()
            ambiguous = st.checkbox('同时重试状态未知的请求（可能再次计费）')
            risk = st.text_input('包含未知请求时输入“接受重复计费风险”') if ambiguous else ''
            if st.button('重新排队失败任务，并保持暂停'):
                n = service.retry_errors(eid,ambiguous,risk)
                st.success(f'{n} 个任务已重新排队；需再次点击恢复。已记录的待核对费用仍保留。')
        with st.expander('核对未知费用（以供应商账单为依据）'):
            pending_costs = db.rows('''SELECT a.id,a.task_id,a.status,a.reservation,a.error_code FROM attempts a
                JOIN tasks t ON t.id=a.task_id WHERE t.experiment_id=%s AND a.cost IS NULL
                AND a.status IN ('ambiguous','succeeded') ORDER BY a.id LIMIT 100''',(eid,))
            st.dataframe(pd.DataFrame(pending_costs),hide_index=True)
            if pending_costs:
                aid = st.selectbox('待核对尝试编号',[r['id'] for r in pending_costs])
                actual = st.number_input('账单确认的实际费用',min_value=0.0,value=0.0,format='%.8f')
                reason = st.text_input('核对依据 / 供应商账单记录')
                if st.button('记录核对结果并暂停实验'):
                    service.reconcile(eid,aid,actual,reason)
                    st.rerun()
        workers = db.rows("SELECT id,heartbeat,mode,heartbeat>now()-interval '3 minutes' AS recent FROM workers ORDER BY heartbeat DESC LIMIT 10")
        st.subheader('Worker 心跳')
        st.dataframe(pd.DataFrame(workers),hide_index=True)
        st.subheader('实验事件')
        st.dataframe(pd.DataFrame(db.rows('SELECT kind,detail,created_at FROM events WHERE experiment_id=%s ORDER BY id DESC LIMIT 100',(eid,))),hide_index=True)
    elif section == '结果与导出':
        e = pick_experiment()
        eid = str(e['id'])
        st.caption('无效答案保留原始响应并标记，不静默丢弃。指标接口已预留；正式统计前核对论文的 MAF1 与 1−JS 定义、分组和权重。')
        data = service.preview(eid,100)
        st.dataframe(pd.DataFrame([{k:r[k] for k in ('id','rid','model_idx','language','prompt_idx','question_idx','state','answer','parse_error','cost')} for r in data]),hide_index=True)
        if data:
            tid = st.selectbox('查看原始响应',[r['id'] for r in data])
            raw = next(r for r in data if r['id']==tid)
            st.json(raw['response'] or {'status':raw['state'],'error':raw['error_code']})
        st.subheader('分段下载')
        st.write('每段最多 500 条；下载后把返回的游标填入下一段。完整导出命令见上线指南。')
        after = st.number_input('起始游标（第一段填 0）',min_value=0,value=0)
        mode = st.selectbox('内容',['结果 CSV','结果 JSONL','原始请求 / 响应 / 所有尝试 JSONL'])
        if st.button('准备下载此段'):
            fmt = 'csv' if mode=='结果 CSV' else 'jsonl'
            blob,n,last = page_export(eid,fmt,int(after),raw=mode.startswith('原始'))
            st.download_button(f'下载 {n} 条 · 下一段游标 {last}',blob,file_name=f'opinionsim-{eid}-{after}.{fmt}',mime='text/csv' if fmt=='csv' else 'application/x-ndjson')
        st.download_button('下载实验配置快照',json.dumps(e['config'],ensure_ascii=False,indent=2),file_name=f'config-{eid}.json')
        events = db.rows('SELECT * FROM events WHERE experiment_id=%s ORDER BY id',(eid,))
        st.download_button('下载实验日志 JSONL','\n'.join(json.dumps(r,default=str,ensure_ascii=False) for r in events),file_name=f'events-{eid}.jsonl')
    else:
        st.markdown((Path(__file__).parent/'docs/UI_HELP.md').read_text())
except (ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
    st.error('输入检查未通过：'+str(exc))
except Exception:
    st.error('操作未完成。请刷新状态并检查云端日志；平台不会在页面内自动重发模型请求。')
