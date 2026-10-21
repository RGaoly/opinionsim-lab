"""Public, zero-credential Streamlit experience; production entry is app.py."""
import copy
import json
import os
import uuid
from collections import Counter
from pathlib import Path
import pandas as pd
import streamlit as st
from opinionsim import demo
from opinionsim.domain import PROFILE_FIELDS,anonymize,read_csv,render,sha,validate_config,validate_template

st.set_page_config(page_title='OpinionSim Lab · 免费体验',page_icon='◉',layout='wide')
st.markdown('''<style>
html,body,[class*="css"] {font-family:Inter,"PingFang SC",sans-serif;}
.block-container {max-width:1420px;padding-top:2.4rem;padding-bottom:3rem;}
h1,h2,h3 {color:#142c41;letter-spacing:-.035em;} h1 {font-weight:700;}
[data-testid="stSidebar"] {background:#142d43;}
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {color:#e8f0f7;}
[data-testid="stSidebar"] [data-baseweb="select"] * {color:#142d43;}
[data-testid="stMetric"] {background:#fff;border:1px solid #e0e7ee;border-radius:12px;padding:18px;}
[data-testid="stMetricLabel"] {color:#66798a;font-size:.85rem;}
.hero {background:linear-gradient(110deg,#143349,#185653);border-radius:16px;padding:28px 30px;color:#fff;margin:14px 0 24px;}
.hero h2 {color:#fff;margin:0 0 8px;font-size:1.7rem;}.hero p {color:#d1e2e4;margin:0;line-height:1.8;}
.eyebrow {color:#07877e;font-size:.74rem;font-weight:700;letter-spacing:.18em;}
.step {color:#66798a;font-size:.9rem;padding:8px 0;}
div.stButton>button[kind="primary"] {background:#087f78;border-color:#087f78;}
</style>''',unsafe_allow_html=True)

if 'lab_demo' not in st.session_state:
    st.session_state.lab_demo=demo.workspace()
lab=st.session_state.lab_demo
PAGES=['项目总览','调查数据','模型与密钥','提示语版本','配置实验','运行监控','结果与导出','上线与方法']

with st.sidebar:
    st.title('◉ OpinionSim')
    st.caption('LAB / 民意模拟研究工作台')
    st.divider()
    page=st.radio('工作区',PAGES,key='demo_page',label_visibility='collapsed')
    st.divider()
    pid=st.selectbox('当前项目',[p['id'] for p in lab['projects']],
                     format_func=lambda x:next(p['name'] for p in lab['projects'] if p['id']==x),key='demo_project')
    st.caption('免费体验版 · 零 API 调用\n\n当前会话暂存，断开或重启后可能重置。')
    st.link_button('GitHub 源码 ↗','https://github.com/RGaoly/opinionsim-lab',use_container_width=True)
    if st.button('重置我的体验',use_container_width=True):
        for key in list(st.session_state):
            if key.startswith('demo_') or key=='lab_demo':
                del st.session_state[key]
        st.rerun()

st.markdown('<span class="eyebrow">OPINIONSIM LAB / RESEARCH WORKSPACE</span>',unsafe_allow_html=True)
st.title(page)
st.caption('免费公开体验 · 所有结果均为合成模拟，不代表论文结论 · 不接受真实密钥或长期保存研究数据')
project=next(p for p in lab['projects'] if p['id']==pid)
datasets=[d for d in lab['datasets'] if d['project_id']==pid]
exps=[e for e in lab['experiments'] if e['project_id']==pid]


def select_exp():
    if not exps:
        st.info('请先到“配置实验”创建模拟草稿。')
        st.stop()
    ids=[e['id'] for e in reversed(exps)]
    eid=st.selectbox('选择模拟实验',ids,format_func=lambda x:next(e['name'] for e in exps if e['id']==x),key='demo_exp_'+page)
    return next(e for e in exps if e['id']==eid)


try:
    if page=='项目总览':
        st.markdown('<div class="hero"><h2>把实验设计，变成可追溯的研究。</h2><p>从调查画像到提示语版本，从 96 个实验条件到每一次响应。<br>先用免费合成示例，走完你的第一轮民意模拟。</p></div>',unsafe_allow_html=True)
        a,b,c,d=st.columns(4)
        a.metric('实验条件','96','2 模型 × 2 语言 × 4 提示 × 6 题',delta_color='off')
        b.metric('合成受访者',sum(len(x['people']) for x in datasets))
        c.metric('当前项目实验',len(exps))
        d.metric('真实 API 费用','¥ 0.00','体验期间始终为零',delta_color='off')
        st.write('')
        left,right=st.columns([1.4,1],gap='large')
        with left:
            st.subheader(project['name'])
            with st.form('demo_notes'):
                notes=st.text_area('研究说明与过程记录',project['notes'],height=100)
                if st.form_submit_button('保存会话记录'):
                    project['notes']=notes
                    st.success('已暂存到当前会话')
            with st.expander('创建另一个研究项目'):
                with st.form('demo_create_project',clear_on_submit=True):
                    name=st.text_input('新项目名称',max_chars=80)
                    if st.form_submit_button('创建项目',type='primary'):
                        if not name.strip():
                            raise ValueError('请填写项目名称')
                        if len(lab['projects'])>=10:
                            raise ValueError('体验版每会话最多 10 个项目，请重置后继续')
                        new_id=str(uuid.uuid4())
                        lab['projects'].append({'id':new_id,'name':name.strip(),'notes':''})
                        lab['prompts'][new_id]=copy.deepcopy(demo.config()['prompts'])
                        st.success('已创建，请在左侧切换项目')
        with right:
            st.subheader('开始一次研究')
            st.markdown('① **调查数据**：查看合成画像与脱敏流程\n\n② **提示语版本**：编辑中英文实验条件\n\n③ **配置实验**：估算 192,000 次调用的规模\n\n④ **运行监控**：体验暂停、恢复和失败重试\n\n⑤ **结果与导出**：检查模拟原始响应')
            st.info('已预置 288 条完成的合成结果，可直接到“结果与导出”查看。')
    elif page=='调查数据':
        st.info('请仅上传自行生成的合成 CSV。文件会传到 Streamlit 服务器内存中处理；本体验版不写入文件或数据库，会话结束后可能丢失。')
        st.download_button('下载合成调查 CSV 模板',(demo.ROOT/'examples/survey.csv').read_bytes(),'synthetic-survey.csv','text/csv')
        if st.button('为当前项目添加内置合成数据'):
            if len(datasets)>=10:
                raise ValueError('每项目最多 10 个体验数据集')
            lab['datasets'].append({'id':str(uuid.uuid4()),'project_id':pid,'name':'合成调查 · 3 人','people':demo.sample_people()})
            st.rerun()
        upload=st.file_uploader('上传合成 CSV（UTF-8，最多 2 MB / 100 行）',type=['csv'],key='demo_upload')
        if upload:
            if upload.size>2*1024*1024:
                raise ValueError('体验上传上限为 2 MB')
            fields,records=read_csv(upload.getvalue())
            if len(records)>100:
                raise ValueError('体验上传上限为 100 行')
            chosen=st.multiselect('保留的人口统计字段',sorted(PROFILE_FIELDS),
                                  default=[k for k in ['age','gender','education','region'] if k in fields])
            mapping={target:st.selectbox(f'{target} 对应的 CSV 列',fields,index=fields.index(target) if target in fields else 0,key='demo_map_'+target) for target in chosen}
            truth={f'q{i}':f'q{i}' for i in range(1,7) if f'q{i}' in fields}
            if 'demo_upload_salt' not in st.session_state:
                st.session_state.demo_upload_salt=os.urandom(32)
            clean=anonymize(records,mapping,truth,st.session_state.demo_upload_salt)
            st.subheader('去标识化预览')
            st.dataframe(pd.DataFrame([{'rid':r['rid'],**r['profile']} for r in clean[:10]]),hide_index=True)
            approved=st.checkbox('确认该文件全部为合成数据，并已检查去标识化结果')
            if st.button('暂存此合成数据集',disabled=not approved,type='primary'):
                if len(datasets)>=10:
                    raise ValueError('每项目最多 10 个体验数据集')
                lab['datasets'].append({'id':str(uuid.uuid4()),'project_id':pid,'name':upload.name,'people':clean})
                st.success('已暂存到当前会话')
        st.subheader('当前项目数据集')
        for ds in datasets:
            with st.expander(f'{ds["name"]} · {len(ds["people"])} 人',expanded=len(datasets)==1):
                st.dataframe(pd.DataFrame([{'rid':r['rid'],**r['profile']} for r in ds['people'][:20]]),hide_index=True)
                st.caption('真实回答独立保存于合成记录，未放入人物画像；年龄按十岁分组。去标识化不等于彻底匿名。')
    elif page=='模型与密钥':
        st.subheader('两种合成模型，零真实调用')
        st.dataframe(pd.DataFrame([{'模型':f'Mock {i}','用途':'演示输入、响应与实验条件','API 调用':'不发送','真实费用':'0'} for i in (1,2)]),hide_index=True)
        st.info('体验版不提供 API Key 输入框，也不会读取云端密钥。正式版在你自己的私有环境中加密保存凭据。')
        st.subheader('正式实验中的凭据流程')
        st.markdown('录入有权使用的供应商凭据 → 加密保存 → 设置限速和供应商额度 → 核准单个实验预算 → 明确授权后执行。')
        st.caption('网页、公开 GitHub 仓库和导出文件均不应包含真实密钥。正式版部署说明在 GitHub 中保留。')
    elif page=='提示语版本':
        st.warning('以下中英文模板用于体验流程，尚未核对论文原文。保存会新增版本，已创建实验的快照不变。')
        versions=lab['prompts'][pid]
        names=list(dict.fromkeys(p['name'] for p in versions))
        selected=st.selectbox('提示语类型',names)
        latest=max((p for p in versions if p['name']==selected),key=lambda p:p['version'])
        with st.form('demo_prompt_'+selected):
            zh=st.text_area('中文模板',latest['body'],height=175)
            en=st.text_area('English template',latest['body_en'],height=175)
            st.caption('变量：{profile}、{question}、{choices}、{language}。字面花括号请双写。')
            if st.form_submit_button('保存新版本',type='primary'):
                validate_template(zh)
                validate_template(en)
                versions.append({'name':selected,'version':latest['version']+1,'body':zh,'body_en':en,'sha256':sha({'zh':zh,'en':en})})
                st.success(f'已保存 {selected} / v{latest["version"]+1}')
        st.dataframe(pd.DataFrame([{k:p[k] for k in ('name','version','sha256')} for p in reversed(versions)]),hide_index=True)
    elif page=='配置实验':
        if not datasets:
            st.info('先到“调查数据”为当前项目添加合成数据。')
            st.stop()
        cfg=demo.config()
        dsid=st.selectbox('体验数据集',[d['id'] for d in datasets],format_func=lambda x:next(d['name'] for d in datasets if d['id']==x))
        ds=next(d for d in datasets if d['id']==dsid)
        name=st.text_input('实验名称','我的第一次 96 条件实验',max_chars=100)
        versions=lab['prompts'][pid]
        chosen=[]
        with st.expander('四种提示语的精确版本',expanded=True):
            cols=st.columns(4)
            for col,prompt_name in zip(cols,[p['name'] for p in cfg['prompts']]):
                options=[p for p in versions if p['name']==prompt_name]
                version=col.selectbox(prompt_name,[p['version'] for p in reversed(options)],key='demo_version_'+prompt_name)
                chosen.append(copy.deepcopy(next(p for p in options if p['version']==version)))
        cfg['prompts']=chosen
        cols=st.columns(2)
        for i,col in enumerate(cols):
            with col:
                st.subheader(f'模型 {i+1} · 模拟')
                cfg['models'][i]['label']=st.text_input('模型显示名称',f'Mock {i+1}',key=f'demo_model_{i}',max_chars=50)
                cfg['models'][i]['input_price']=st.number_input('假设每百万输入 Token 单价',min_value=0.0,max_value=10000.0,value=1.0,key=f'demo_input_{i}')
                cfg['models'][i]['output_price']=st.number_input('假设每百万输出 Token 单价',min_value=0.0,max_value=10000.0,value=3.0,key=f'demo_output_{i}')
        cfg['currency']=st.selectbox('估算币种',['CNY','USD'])
        a,b,c=st.columns(3)
        population=a.number_input('计划受访者数（仅用于估算）',min_value=1,max_value=100000,value=2000)
        cfg['repetitions']=int(b.number_input('计划重复次数',min_value=1,max_value=100,value=1))
        budget=c.number_input('假设预算上限',min_value=0.0,max_value=1000000.0,value=300.0)
        a,b=st.columns(2)
        cfg['expected_input_tokens']=int(a.number_input('平均输入 Token 估计',min_value=1,max_value=100000,value=600))
        cfg['expected_output_tokens']=int(b.number_input('平均输出 Token 估计',min_value=1,max_value=8192,value=150))
        cfg['max_output_tokens']=max(512,cfg['expected_output_tokens'])
        with st.expander('六道中英文合成问题 JSON'):
            text=st.text_area('题目与选项',json.dumps(cfg['questions'],ensure_ascii=False,indent=2),height=230)
            cfg['questions']=json.loads(text)
        validate_config(cfg)
        estimate=demo.estimate(cfg,int(population))
        calls=int(population)*96*cfg['repetitions']
        a,b,c=st.columns(3)
        a.metric('计划请求数',f'{calls:,}')
        b.metric('假设 API 原价',f'{estimate:,.2f} {cfg["currency"]}')
        c.metric('体验版真实费用','0.00')
        if estimate>budget:
            st.warning('假设费用超过预算。正式版会按请求预留费用并拦截超额；这里仅作估算演示。')
        st.info(f'正式计划为 {calls:,} 次；本次只为最多 3 名合成受访者生成至多 288 个模拟任务，重复次数仅影响估算。')
        fail=st.checkbox('加入一次模拟失败，体验重试流程',value=True)
        if st.button('创建模拟实验草稿',type='primary'):
            if not name.strip():
                raise ValueError('实验名称不能为空')
            if len(exps)>=10:
                raise ValueError('每项目最多 10 个模拟实验')
            exp=demo.make_experiment(name.strip(),cfg,ds['people'],pid,int(population),fail)
            exp['hypothetical_budget']=budget
            lab['experiments'].append(exp)
            st.success('模拟草稿已创建。到“运行监控”体验排队与重试。')
    elif page=='运行监控':
        exp=select_exp()
        st.info('手动模拟进度：以下按钮只更新本次会话，不启动真实后台任务。关页面后不会继续这轮演示。')
        labels={'draft':'草稿','queued':'已排队','running':'运行中','paused':'已暂停','completed':'已完成','completed_errors':'完成，含失败项'}
        counts=Counter(t['state'] for t in exp['tasks'])
        done=counts['succeeded']+counts['failed']
        st.progress(done/len(exp['tasks']),text=f'模拟状态：{labels[exp["state"]]} · {done} / {len(exp["tasks"])}')
        a,b,c,d=st.columns(4)
        a.metric('模拟成功',counts['succeeded'])
        b.metric('模拟失败',counts['failed'])
        c.metric('计划正式请求',f'{exp["planned_calls"]:,}')
        d.metric('真实 API 费用','0.00')
        a,b,c,d=st.columns(4)
        active=exp['state'] in ('queued','running')
        if a.button('模拟排队 / 恢复',type='primary',disabled=not counts['queued']):
            demo.resume(exp)
            st.rerun()
        if b.button('模拟暂停',disabled=not active):
            demo.pause(exp)
            st.rerun()
        if c.button('模拟推进 48 条',disabled=not active):
            demo.advance(exp,48)
            st.rerun()
        if d.button('完成本轮模拟',disabled=not active):
            demo.advance(exp,288)
            st.rerun()
        if st.button('重新排队模拟失败项',disabled=not counts['failed']):
            demo.retry(exp)
            st.rerun()
        st.caption('失败重试保留历史尝试，重排后保持暂停，需再次恢复。正式版由独立 Worker 与数据库持续运行。')
        st.subheader('模拟事件记录')
        st.dataframe(pd.DataFrame(list(reversed(exp['events']))),hide_index=True)
    elif page=='结果与导出':
        exp=select_exp()
        rows=demo.result_rows(exp)
        st.warning('全部为合成模拟结果，mock=true；不能作为论文证据或对模型能力的评价。')
        a,b,c=st.columns(3)
        a.metric('模拟记录',len(rows))
        b.metric('模拟成功',sum(r['state']=='succeeded' for r in rows))
        c.metric('真实 API 调用','0')
        models=st.multiselect('按模型筛选',list(dict.fromkeys(r['model'] for r in rows)),default=list(dict.fromkeys(r['model'] for r in rows)))
        langs=st.multiselect('按语言筛选',['zh','en'],default=['zh','en'])
        filtered=[r for r in rows if r['model'] in models and r['language'] in langs]
        st.dataframe(pd.DataFrame(filtered),hide_index=True,use_container_width=True)
        st.subheader('原始模拟请求与响应')
        completed=[t for t in exp['tasks'] if t['attempts']]
        if completed:
            tid=st.selectbox('模拟任务编号',[t['id'] for t in completed])
            task=next(t for t in completed if t['id']==tid)
            st.json({'mock':True,'task_id':tid,'attempts':task['attempts']})
        a,b,c=st.columns(3)
        a.download_button('下载全部结果 CSV',('\ufeff'+demo.export(exp,'csv')).encode(),'opinionsim-mock-results.csv','text/csv')
        b.download_button('下载全部结果 JSONL',demo.export(exp),'opinionsim-mock-results.jsonl','application/x-ndjson')
        c.download_button('下载模拟原始尝试 JSONL',demo.export(exp,raw=True),'opinionsim-mock-attempts.jsonl','application/x-ndjson')
        st.caption('下载包含本实验全部模拟记录，不受表格筛选影响。')
        st.download_button('下载配置快照',json.dumps({'mock':True,'config_sha256':exp['config_sha256'],'config':exp['config']},ensure_ascii=False,indent=2),'opinionsim-mock-config.json','application/json')
    else:
        st.subheader('你正在体验什么')
        st.markdown('这是公开、免费的会话演示版。源码同时保留正式研究版：Streamlit 前端、独立 Python Worker、PostgreSQL 持久数据库与队列。')
        st.dataframe(pd.DataFrame([
            {'能力':'项目、提示语、实验配置','免费体验':'当前会话暂存','正式版':'数据库持久保存'},
            {'能力':'模型响应','免费体验':'合成模拟，最多 288 条','正式版':'明确授权后调用真实 API'},
            {'能力':'暂停 / 恢复 / 重试','免费体验':'手动模拟状态','正式版':'独立云端 Worker 执行'},
            {'能力':'关闭 Mac 后继续实验','免费体验':'不提供','正式版':'云端 Worker 和数据库运行时支持'},
            {'能力':'MAF1 / 1−JS','免费体验':'仅说明口径','正式版':'通用函数接口，论文口径待核对'}]),hide_index=True)
        st.markdown('正式入口为 `app.py`，本体验入口为 `streamlit_app.py`。部署说明、备份恢复和测试均在 GitHub 仓库中。')
        st.link_button('查看正式版部署说明','https://github.com/RGaoly/opinionsim-lab/blob/main/docs/DEPLOY.md')
        st.caption('论文原文与附录尚未核对，六题和四套提示语均为示例。正式研究前必须替换并核准方法。')
except (ValueError,KeyError,TypeError,UnicodeDecodeError) as exc:
    st.error('请检查输入：'+str(exc))
