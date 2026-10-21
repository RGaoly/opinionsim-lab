# 上线指南

本包没有云账号授权，不包含真实 Key，没有已部署的生产网址。下面的创建服务器、购买托管、备案、账户认证和 API 授权均需要你本人完成。登录口令与 Key 不要发到聊天或放入 Git。

## 路线 A：学生云服务器，优先省现金

推荐先申请校内已有 Linux 环境；否则比较阿里云学生 ECS。99 元/年是否可购、地域和资源限制以认证后的订单为准。2 vCPU / 2 GB RAM 可作为个人试运行起点，4 GB 对导入和导出更宽裕。API 实验通常不需要 GPU。

这是同一云主机中的**独立 Web、Worker 和 PostgreSQL 容器**，不是在 Mac 或 Streamlit 页面中跑实验。数据库持久卷在云主机磁盘上，单机硬件故障仍需备份恢复。

### 1. 你选择并创建服务器

- 选择供应商提供的 Ubuntu LTS、足够磁盘和公网访问条件；本包建议先预留至少 20 GB 可用空间，正式批量前按响应实际大小估算容量。
- 通过厂商当前文档安装 Docker Engine 和 Docker Compose 插件，并设为开机启动。
- 安全组仅允许必要的管理来源；PostgreSQL 不开放公网端口。
- 若使用中国内地节点并对外提供网站，按厂商备案流程办理。正式网址需要你提供域名并配置 DNS。[阿里云备案场景](https://help.aliyun.com/zh/icp-filing/what-scenarios-need-to-be-filed-in-aliyun)。

### 2. 上传与生成机密配置

把本目录上传到云主机，例如 `~/opinionsim-lab`。进入该目录后：

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python setup_secrets.py
```

脚本交互式要求至少 12 字符口令，生成随机数据库密码、Fernet 加密主密钥和 PBKDF2 口令哈希，写入权限 600 的 `.env`；已有文件不会覆盖。请把 `.env` 另外保存在你控制的安全密码库。丢失 Fernet 主密钥后，数据库中的 API Key 将无法解密，需重新录入。

`.env` 中 `ALLOW_PAID_API=false` 保持默认。它既被 Web 也被 Worker 读取。

### 3. 启动常驻服务

```sh
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 worker
```

`-d` 使容器独立于 SSH 会话运行。重启策略会在 Docker/服务器重启后恢复服务；断电恢复前的未知模型请求按租约恢复规则进入人工核对，不会盲目重发。

默认前端只绑定云主机回环地址，本人测试可通过安全的 SSH 本地转发访问：

```sh
ssh -L 8501:127.0.0.1:8501 YOUR_USER@YOUR_SERVER
```

在 Mac 浏览器打开 `http://localhost:8501`。Mac 关机只会断开访问隧道，云端容器仍继续工作。此方式不是公开生产网址，仍遵循学校及供应商访问管理要求。

### 4. 配置正式 HTTPS 网址

完成域名、DNS、必要备案及安全组 80/443 配置后，在 `.env` 中把 `DOMAIN=lab.example.org` 改成你的域名，再启动附加代理：

```sh
docker compose -f compose.yaml -f compose.https.yaml up -d --build
```

Caddy 自动申请/续期证书并转发 Streamlit WebSocket。首次需保证域名解析正确且 80/443 可访问；证书数据在命名卷中保存。正式地址为 `https://你的域名`，必须登录研究室口令。对敏感调查数据，建议额外加学校身份代理或限制访问来源。当前版本没有多人权限隔离。

### 5. 免费验证

- 登录，点“创建免费演示项目”。
- 在“运行监控”选择演示实验，点排队。共 288 次 Mock，不发送外网请求。
- 运行到一半关闭浏览器，稍后重开；核对任务继续增长。
- 暂停、恢复，检查成功数、心跳、费用为 0，以及结果 JSONL。
- 在云服务控制台重启 Worker，确认任务状态仍在数据库中。正在发出的请求可能进入 `ambiguous`，需要核对；这是有意保守的恢复方式。

### 6. 备份和恢复

**持久卷不是备份。**至少每日备份，并在正式实验前另存一次，复制到独立存储。备份包含调查画像与真实回答，需加密并限制访问。可使用云厂商备份，也可执行：

```sh
mkdir -p backups
docker compose exec -T db pg_dump -U opinionsim -d opinionsim -Fc > backups/opinionsim.dump
```

请自行按日期命名、设置保留期并将备份复制到独立位置；`.gitignore` 已排除 `backups/`。需要自动化时，由服务器定时任务或云备份执行上述操作，并设置失败告警；本次没有替你创建付费备份服务或定时任务。

恢复应先在**新建的空数据库/独立测试环境**验证：

```sh
docker compose exec -T db pg_restore -U opinionsim -d NEW_EMPTY_DATABASE --no-owner < backups/opinionsim.dump
```

`NEW_EMPTY_DATABASE` 需你预先创建为用于恢复的独立空库；不要直接覆盖当前生产库。更换目标库前先停止 Worker、调整 `DATABASE_URL` 并确认加密主密钥相同。

不要执行 `docker compose down -v`；它会删除数据库卷。正常更新代码用 `docker compose up -d --build`，普通停止用 `docker compose stop`。

## 路线 B：Render，优先省维护

已提供按官方当前 Blueprint 字段编写的 `render.yaml`，固定同一区域 `singapore`，两个付费 512 MB 实例和一个付费 PostgreSQL 256 MB / 5 GB 实例。名义起步约 7 + 7 + 6 美元/月，再加存储等，5 GB 存储按 0.30 美元/GB/月示例，总计约 21.5 美元/月；下单以当时控制台报价为准。[价格](https://render.com/pricing)、[Blueprint 字段](https://render.com/docs/blueprint-spec)。

1. **你操作**：注册 Render，绑定支付方式；把本目录上传到你自己的私有 Git 仓库，根目录保留 `Dockerfile` 和 `render.yaml`。
2. **你操作**：本地或服务器运行 `setup_secrets.py`，只把 `APP_PASSWORD_HASH` 和 `FERNET_KEY` 对应值通过 Render 机密输入框填入，不提交 `.env`。
3. 在 Render 创建 Blueprint，选择该仓库；检查全部收费项目、区域与 5 GB 数据库存储后确认。该动作会产生托管费用，本次未代做。
4. 初次创建会要求 Web 服务的两个机密值。Worker 的 Fernet Key 通过 Blueprint 引用 Web 环境变量，保证同一主密钥。数据库连接使用 Render 同区域内部地址，数据库公网 IP 列表为空。
5. 等 Web 和 Worker 就绪。Web 自动使用平台提供的 `PORT`，健康路径 `/_stcore/health`。Web 地址由 Render 返回；不要自行猜测。
6. 保持 `ALLOW_PAID_API=false`，运行合成 Mock 实验，检查关浏览器后仍完成。付费 Background Worker 持续运行，仍可能因重部署或故障重启，数据库队列负责保存状态。
7. 配置云监控与数据库备份、账单上限/提醒；检查实际备份保留与恢复权限。容量不能无限增长；用试验实测原始响应大小决定是否扩大数据库或增加对象存储。

不要改用免费 Postgres 或把 Worker 放进免费 Web。Render 免费 Web 会休眠，免费数据库 30 天到期。[后台能力](https://render.com/docs/background-workers)、[免费限制](https://render.com/docs/free)、[区域](https://render.com/docs/regions)。

## 路线 C：Railway 或 Azure 学生额度

可复用同一 Dockerfile，分开创建两个常驻服务：Web `SERVICE_ROLE=web`，Worker `SERVICE_ROLE=worker`，同区域 PostgreSQL，并配置相同 `DATABASE_URL/FERNET_KEY`。仅 Web 公开域名，数据库使用私网/受保护连接。

Railway Hobby 的 5 美元是最低用量承诺，并非三个服务固定总价；Worker 禁用 Serverless/休眠，持久数据库必须挂卷，设置平台消费上限。本文没有提供或验证这些平台的专用自动部署配置。[计费](https://docs.railway.com/pricing/plans)、[Serverless](https://docs.railway.com/deployments/serverless)。

Azure 学生额度需先由你通过认证，核对允许区域和配额，再选择 VM 或容器服务。不要使用会缩到零且无作业恢复保障的配置替代常驻 Worker。

## 正式 API 小试：需要明确授权

1. 获得论文及附录，核对六题、四种提示语、两模型固定版本、中英文、人口画像、温度、思考模式、缺失值与重复次数。示例问题不代表原文。
2. 只录入你有资格使用的 API 凭据。供应商地址需 HTTPS 且在 `API_ALLOWED_HOSTS` 列表。原生 Azure/Claude API 需要额外适配，当前不要假设可直接填入。
3. 到供应商后台检查实际单价、Token 计费、免费额度/券、限额、用完即停与并发限制。实验配置的价格必须统一 CNY 或 USD；不要混用，也不要预先减去尚未核实的优惠。
4. 从少量已授权受访者建独立小试数据集。每 1 人会产生 96 次请求，10 人是 960 次；设置相应小预算。
5. **你决定授权后**，将 Web/Worker 环境变量 `ALLOW_PAID_API` 都改为 `true` 并重启服务。Docker 路线更新 `.env` 后：`docker compose up -d --force-recreate web worker`。Render 路线修改共享环境组后重新部署两个服务。
6. 在该实验的运行监控中输入“授权本实验付费调用”并点击恢复。全局开关不能代替实验授权。录入 Key 或创建草稿本身不会调用 API。
7. 检查真实响应、实际用量、解析成功率和账单，再决定是否授权正式规模。不能仅依据网站是否在线就运行 192,000 次。

### 预算与恢复语义

- 每次领取持有实验行锁，检查 `spent + uncertain + reserved + next_reservation <= budget` 后才能发出。
- 输入按 UTF-8 字节数加协议余量保守估算，输出按 `max_tokens` 预留；特殊分词、阶梯/缓存价和供应商计费不能由该算法严格担保。特殊模型需增加精确 Token 计数与供应商价格适配；供应商硬限额仍是最终控制。
- 使用返回 usage 核算已知费用；缺少 usage 的已完成请求、超时/5xx、崩溃时未确认的请求保留费用等待人工核对。
- 429 最多五次自动尝试，退避 2–300 秒。参数/鉴权错误保存代码，修正后手动重试。无效答案保留原始响应，不自动重新采样，以免改变实验分布。
- 任务租约 10 分钟；到期转 `ambiguous`，不自动重发。晚到结果只保留证据，不重复记账。
- 暂停会阻止后续领取；正在执行的请求仍会完成并计费。
- 未知请求重试前需输入“接受重复计费风险”，历史预留保留在待核对项；按账单填写实际费用、核对依据后才能调整记账。
- 平台无法保证跨数据库与外部供应商的严格 exactly-once。保守的未知状态处理是为了避免自动制造重复支出。

## 完整导出

页面提供每段 500 条的结果 CSV、结果 JSONL、全部尝试原始 JSONL；最后游标用于下一段。配置、实验日志也可下载。完整数据不要在低内存页面一次载入。

在已配置环境变量的运行环境中，使用实验实际 UUID：

```sh
python -m opinionsim.export EXPERIMENT_UUID --format csv --output results.csv
python -m opinionsim.export EXPERIMENT_UUID --format jsonl --output results.jsonl
python -m opinionsim.export EXPERIMENT_UUID --format jsonl --raw --output attempts.jsonl
```

Docker 路线可使用宿主机输出重定向，避免非 root 容器对绑定目录的权限问题：

```sh
mkdir -p exports
docker compose exec -T web python -m opinionsim.export EXPERIMENT_UUID --format csv --output /tmp/results.csv
docker compose cp web:/tmp/results.csv exports/results.csv
docker compose exec -T web python -m opinionsim.export EXPERIMENT_UUID --raw --output /tmp/attempts.jsonl
docker compose cp web:/tmp/attempts.jsonl exports/attempts.jsonl
```

工具使用数据库服务端游标，按行写出，保留失败、解析错误、原始尝试与使用量。CSV 对可触发电子表格公式的字符串增加前导单引号；需要无改动文本时使用 JSONL。导出时含去标识化画像关联及真实答案，应按调查数据权限保存。

## 扩展统计与厂商 Batch

`opinionsim.analysis` 已提供通用 `macro_f1(truth, predicted, labels)` 和 `one_minus_js(p,q)`。后者使用 base-2 JS 散度，不取平方根。论文 MAF1 命名、缺失值、调查权重、子组和重复抽样等需先核对，当前没有自动生成论文结论。

厂商原生 Batch 尚未实现。若用百炼 Batch 五折，应新增提交/轮询/逐项回收/成本对账适配器，不能只把普通请求配置单价除以二。先确认论文需要的精确模型版本和所有参数都在 Batch 中支持。
