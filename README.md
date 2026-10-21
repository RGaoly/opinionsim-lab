# OpinionSim Lab

为《思维链的影响：大语言模型模拟民意的实证研究》准备的个人研究平台可部署版本。

提供两种运行方式：**免费公开体验版**（`streamlit_app.py`）与**私有正式研究版**（`app.py` + 独立 Worker + PostgreSQL）。论文原文和附录尚未获取，内置问卷和四组中英文提示语均为合成流程示例，不能作为已复现论文的方法或结果。

## 免费体验版

公开源码：[RGaoly/opinionsim-lab](https://github.com/RGaoly/opinionsim-lab)。Streamlit 访问链接将在部署完成并验证后补入。

```sh
pip install -r requirements.txt
streamlit run streamlit_app.py
```

- 无需数据库、登录口令或 API Key；不会调用模型或产生 API 费用。
- 含 3 名合成受访者、288 条合成响应，支持项目、脱敏预览、中英文提示语版本、96 条件配置、费用估算、模拟暂停/恢复/重试和 CSV/JSONL 导出。
- 2,000 人 × 96 条件 = 192,000 次仅用于估算；每轮最多生成 288 个内存中的模拟任务。
- 体验内容仅在当前 Streamlit 会话内暂存，会话断开或服务重启后可能重置；不同访客相互隔离，不上传真实调查或密钥。
- 模拟进度由按钮推进，关闭页面后不会继续；长期实验需使用下面的正式架构。
- Streamlit Community Cloud：公开仓库、`main` 分支、入口 `streamlit_app.py`、Python 3.12；不设置任何 Secrets，不部署 Worker 或数据库。

本次免费体验发布不购买云资源，不运行付费实验。仓库中的云模板仅供后续由使用者自行部署，使用前应核实成本和账户权限。

## 架构

```mermaid
flowchart LR
    A[浏览器 / Mac] -->|HTTPS + 登录口令| B[Streamlit 前端]
    B <-->|项目 / 数据 / 配置 / 进度| C[(PostgreSQL 持久数据库与队列)]
    D[独立 Python Worker] <-->|领取任务 / 预留预算 / 写回结果| C
    D -->|已授权的 API 请求| E[模型供应商]
    C --> F[独立备份 / CSV / JSONL]
```

前端不调用模型、不启动后台线程执行批量实验。云端 Worker 与数据库持续运行时，关闭 Mac 不影响实验。

## 已实现

- 单研究者口令登录；项目创建、研究记录。
- CSV 上传、字段白名单、年龄分箱、随机编号、疑似个人标识拦截；真实答案与提示语分离。
- 加密 API Key、允许域名列表、凭据停用、按凭据共享的 RPM 限速。
- 四组双语提示语版本、内容哈希；实验配置快照。
- 固定 2 模型 × 2 语言 × 4 提示 × 6 题，支持受访者样本与重复次数；2,000 人 = 192,000 任务。
- Token 预算估算、每次请求的事务预算预留、预算用尽拦截。
- PostgreSQL 队列、并发领取、防止同任务同时领取、暂停/恢复、429 退避重试。
- 崩溃/超时的未知请求保守记账，人工核对及显式重试；保留全部尝试证据。
- 进度、费用、Worker 心跳、实验事件；原始请求/响应保存。
- 结果预览，分段 CSV/JSONL 下载，服务端完整流式导出。
- 通用 macro-F1 与 1−JS 函数接口，尚未核定论文统计聚合规则。
- Docker Compose 持久卷部署，HTTPS 反向代理配置，Render 付费三服务 Blueprint。

## 从免费演示开始

在云服务器或安装了 Docker Compose 的测试机上：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python setup_secrets.py
docker compose up -d --build
```

本人远程访问、HTTPS、云端部署与备份见 [上线指南](docs/DEPLOY.md)。登录后点“创建免费演示项目”，到“运行监控”排队即可执行 288 个模拟任务，费用为 0。

## 重要边界

- 这是**单研究者私有工作台**，共用口令不提供多人身份、项目权限隔离、机构 SSO。不要给互不信任的研究者共用。
- 当前模型适配器支持 Chat Completions 兼容接口。部分模型需要不同输出长度参数/思考参数，应先校验；不宣称兼容所有模型。
- 自建队列逐次 API 调用不是厂商原生 Batch，不自动获得 Batch 折扣。
- 金额按配置中的币种与单价记账；缓存、阶梯价格、额外推理计价等需要核对。应用的保守 Token 预留不能代替供应商端计费上限。
- 真实调用要同时满足云端 `ALLOW_PAID_API=true` 和单实验输入“授权本实验付费调用”。默认关闭。
- 导出保留缺失与解析错误，避免只报告成功回答而引入选择偏差。
- 数据库包含去标识化调查画像、真实答案和响应。去标识化不是匿名化；是否可上传外部服务仍取决于数据授权。

## 测试

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
# 要验证队列，请指定专用测试数据库：测试会创建并删除独立临时 schema。
TEST_DATABASE_URL=postgresql://user:password@localhost:5432/testdb .venv/bin/python -m pytest -q
```

未配置 `TEST_DATABASE_URL` 时，数据库测试会明确跳过。集成测试全部使用模拟响应，不访问真实 API。测试范围与实测结果见 [验证记录](docs/VALIDATION.md)。

## 上线前需要你提供/操作

1. 申请校内资源或认证学生云权益，选择区域和数据库方案，完成相应账户与费用确认。
2. 将本目录上传到你自己的服务器或私有 Git 仓库。
3. 在云端保存独立加密主密钥、数据库连接和登录口令哈希，完成 HTTPS 与备份。
4. 获得论文、附录和调查数据授权，替换示例内容，确定模型与计费规则。
5. 自行决定是否授权小额真实试验；确认后再逐步扩展。

如需正式部署，先阅读 [上线指南](docs/DEPLOY.md) 并确认云端持久数据库、独立 Worker、数据授权与预算。
