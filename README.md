# 律序 · 法律工作台

基于两份用户提供的法律技能包改造的可运行首版。Vue 3 + TypeScript 前端，FastAPI + CrewAI 1.15.22 后端，MySQL 8.4 保存业务状态，腾讯云 COS 保存原件和页面图像。支持 DeepSeek 直连、腾讯云 TokenHub 和可选法律检索 MCP。

## 本地开发启动

环境：Python 3.12、uv、Node.js 20.19+ 或 22.12+，以及 Docker（仅用于本地 MySQL）。应用和 Worker 在本机运行。

```bash
cd /Users/brown/program/www/lawer-agent
python3 scripts/setup.py
python3 scripts/start.py
```

打开 http://127.0.0.1:8891 。登录账号在项目根目录 `.env` 的 `APP_USERNAME`（默认 `admin`），密码在 `APP_PASSWORD`，首次初始化随机生成。从旧版升级会增加账号并沿用原密码，已有案件不变；旧会话失效后需重新登录。修改账号或密码后重启应用即可生效。启动器会安装锁定依赖、构建 Vue、启动专用 MySQL、执行迁移，同时运行 API 和 Worker。`Ctrl+C` 停止应用进程，MySQL 数据卷保留。

依赖已安装后可用 `python3 scripts/start.py --skip-install`。已有 MySQL 时在根 `.env` 修改 `DATABASE_URL`，使用 `--external-mysql`；需预先创建专用数据库并授予用户建表权限。应用端口可用 `--port 8892` 改变。本地 MySQL 只监听 `127.0.0.1:3318`，Compose 项目名为 `lawer-workspace`，不会复用其他项目容器。

前端热更新：另开终端在 `frontend` 运行 `npm run dev`，打开 http://127.0.0.1:5174 ，默认代理到 8891。

## Dockerfile 构建与 docker run 启动（/lawer/）

镜像参考 Jiami 的单容器方式，内部运行 Nginx、API 和 Worker，MySQL 独立运行。容器监听 80，默认映射宿主机 8088；前端资源、API、SSE、原件预览和导出统一使用 `/lawer/`。登录 Cookie 由容器 Nginx 限定到 `/lawer/`。

部署只需要 Docker 和可连接的 MySQL，无需在宿主机安装 Node.js、Python、uv 或 Docker Compose。前端构建和 Python 依赖安装都在 Dockerfile 内完成。

**1. 构建镜像。** 在部署服务器的本项目目录执行：

```bash
docker build -t lawer-agent:2026.10.05-1 .
```

**2. 准备运行配置。** 首次部署复制模板；已有 `.env.docker` 时直接编辑原文件，不要覆盖：

```bash
cp -n docker/lawer.env.example .env.docker
chmod 600 .env.docker
```

填写 `.env.docker` 中的 `DATABASE_URL`、`APP_SECRET`、`APP_USERNAME` 和 `APP_PASSWORD`。`APP_SECRET` 首次可用 `openssl rand -hex 32` 生成；已有部署必须沿用原密钥和账号配置。用户名和密码直接写入文件，不加 shell 引号。数据库密码含 `@`、`:`、`/`、`#`、`%` 等字符时，在连接 URL 中做百分号编码。

MySQL 使用已存在的独立服务，与 Jiami 一样不包含在应用镜像内。预先创建专用库 `law_workspace` 和有该库建表、迁移、读写权限的账号；不要指向 Jiami 的业务库。应用启动会自动创建/迁移表，但不会创建数据库或 MySQL 用户。

- 宿主机 MySQL：模板使用 `host.docker.internal:3306`；启动命令保留 `--add-host`。MySQL 必须监听容器可达的地址并允许该账号连接；Linux 上只监听 `127.0.0.1` 的服务通常无法从容器访问。
- 远端 MySQL：将地址、端口替换为实际值，可以去掉 `--add-host`。
- 同一 Docker 网络的 MySQL：启动命令增加 `--network <现有网络名>`，数据库地址使用 MySQL 容器名及内部端口（通常是 `3306`）。

容器中的 `127.0.0.1` 是应用容器自身，不能照搬本地开发 `.env` 的数据库地址。

**3. 启动应用容器。** 以下端口与外部 Nginx 的 `43.155.214.55:8088` 对应：

```bash
docker run -d \
  --name lawer-agent \
  --restart unless-stopped \
  --stop-timeout 45 \
  -p 8088:80 \
  --env-file .env.docker \
  --add-host=host.docker.internal:host-gateway \
  -v lawer_data:/app/.local \
  lawer-agent:2026.10.05-1
```

**4. 查看启动结果。**

```bash
docker logs --tail=100 -f lawer-agent
docker inspect --format '{{.State.Health.Status}}' lawer-agent
```

正常状态从 `starting` 变为 `healthy`。容器先执行数据库迁移，失败则退出；Supervisor 管理 Nginx、API 和 Worker，健康检查验证进程状态及经 Nginx 到 MySQL 的健康接口。

配置只在运行时注入，不进入镜像。`COOKIE_SECURE=true` 用于正式 HTTPS 登录；仅通过 HTTP 直连 IP 调试登录时，需在创建容器时覆盖 `-e COOKIE_SECURE=false`，正式部署恢复为 `true`。登录账号密码来自 `.env.docker`，无需在容器内运行本地 `scripts/start.py`。

MySQL 数据由独立数据库服务持久化，本地文件保存在 `lawer_data` 卷。已有本机 `.local/files` 不会自动迁移到容器卷，如需沿用应先复制并验证文件；已有 COS 文件继续使用原配置。备份时保留数据库、文件卷和 `APP_SECRET`，更换密钥会使数据库中的加密配置无法解密。

外部 Nginx 保留 `/jiami/` 配置，把原来两个 `/a` location 替换为下列内容（也见 `docker/host-nginx.conf.example`）：

```nginx
location = /lawer {
    return 308 /lawer/$is_args$args;
}

location ^~ /lawer/ {
    proxy_pass http://43.155.214.55:8088;
}
```

`proxy_pass` 的上游地址末尾不要加 `/`，外部代理必须保留 `/lawer/`。容器内部将 `/lawer/api/...` 转给后端 `/api/...`，保留 SSE 流式响应。其余 TLS、转发头和超时设置沿用外部配置。对外入口为 `https://tec.zhiquant.com/lawer/`；8088 需允许外部 Nginx 所在主机访问。若更改宿主端口，修改 `docker run` 的 `-p 宿主端口:80` 并同步修改上游。

**更新镜像。** 先备份数据库和文件卷，再构建一个新版本：

```bash
docker build -t lawer-agent:2026.10.05-2 .
docker stop lawer-agent
docker rm lawer-agent
# 再执行上面的 docker run，仅将镜像标签改成 lawer-agent:2026.10.05-2。
```

更新时复用原 `.env.docker`、数据库和 `lawer_data` 卷。删除容器不会删除命名卷；不要删除卷，也不要重新生成 `APP_SECRET`。单纯 `docker restart` 不会应用新镜像。

Docker 构建默认使用当前平台；在 ARM Mac 构建供 x86 Linux 使用的镜像，可用 `docker buildx build --platform linux/amd64 --load -t lawer-agent:2026.10.05-1 .`。也可像 Jiami 一样将版本镜像推到自己的镜像仓库，服务器拉取后执行相同的 `docker run`。

前端 `npm run build` 默认生成 `/lawer/` 版本；本机 `scripts/start.py` 自动以 `VITE_BASE_PATH=/` 构建，保持原来的根路径访问。`--skip-install` 只跳过依赖安装，仍会重新构建本地前端，避免误用 `/lawer/` 产物。Docker 的前缀固定为 `/lawer/`，如要更改，需同步调整容器 Nginx 和健康检查路径并重新构建镜像，不能仅修改运行时环境变量。

## 第一次使用

1. 在“工作台设置”选择 DeepSeek 或 TokenHub，填写该供应商的模型 ID 和 API Key，保存后分别测试文本、图片能力。
2. DeepSeek 默认使用 `deepseek-flash`，模型 ID 可修改。TokenHub 默认地址为 `https://tokenhub.tencentmaas.com/v1`，模型 ID 以控制台可用列表为准。图片能力、JSON 模式独立配置，协议兼容不代表模型支持图片。
3. 配置 COS 地域、存储桶、SecretId、SecretKey，并切换到 COS。存储桶保持私有；后端需要 `HeadBucket`、`PutObject`、`GetObject` 权限。测试按钮仅验证桶可访问，实际上传验证写权限。没有 COS 凭证时可使用本地开发存储。
4. 新建案件，上传 PDF、PNG/JPG/WebP、UTF-8 TXT/MD。每文件最多 20MB，PDF 最多 80 页，图片最多 2500 万像素。
5. 在“法律依据”粘贴法规/案例原文和版本，或导入官方 HTML 网页。来源效力保持“未核验”。支持 gov.cn、npc.gov.cn 网页；动态页面失败时可粘贴正文，PDF 作为素材上传。
6. 勾选素材和依据，填写问题，选择案件分析、民事起诉状草稿或民事答辩状草稿。结果提供引用回看、模型复核意见和 Markdown 导出。

上传和分析均为后台任务。文本 PDF 提取文字层并保留页面图像；图片和扫描页交给图片模型理解。全页视觉识别可检查文字层之外的图表、签章，但不提供鉴定真伪能力。图片模型不可用时明确显示“待图片识别”。

## 四个角色与技能

| 角色 | 加载技能 | 输出 |
|---|---|---|
| 案件与证据分析员 | legal-scenario-router、litigation-workflows | 事实、时间线、证据缺口 |
| 法律研究员 | legal-search-engine、case-retrieval | 法律关系、主张抗辩、来源缺口 |
| 策略与文书起草员 | china-litigation-toolkit、legal-output-formatter | 分节分析或文书草稿 |
| 证据与结论复核员 | legal-verification-workbench | 逐项原文支持、矛盾、不足 |

业务技能在 `law_backend/src/law_backend/skills`；`.agents/skills` 是通过 `crewaiinc/skills` 安装的开发指导。使用 CrewAI 原生 `discover_skills` / `activate_skill` 和 `Agent.skills`，由 Flow 顺序编排角色。角色及分工在 `roles.yaml` 配置。

原始 Desktop 技能包保持原样。改造后的技能保存来源 SHA256 和迁移说明，移除付费 MCP 强制调用、环境专属路径和不适合首版的美国诉讼流程。不是原包全部流程的逐字搬运；首版覆盖中国民事/劳动争议材料分析与民事文书草稿，劳动仲裁等专用文书尚未实现。

## MCP 可选接入

默认关闭，不影响材料解析、分析和文书生成。支持远程 Streamable HTTP / SSE；设置地址和可选 Bearer Token，保存后发现工具，选择只读检索工具和参数。当前不运行本地 stdio 命令。

运行时只调用一个明确配置的检索工具。标准结果格式：

```json
{"sources":[{"title":"来源名称","content":"取得的正文","url":"https://…","version":"2023 年修正","effective_date":"2023-03-15"}]}
```

也兼容 `results` 数组。非结构化文本或没有正文的结果会记录为“待适配/无可引用正文”；网络或鉴权失败记录不可用，并继续已有素材分析。平台专有字段需增加转换器。当前未与北大法宝、元典或诉法法付费服务完成真实账号联调。

## 数据与边界

- 案件、素材元信息、来源版本、执行记录、逐阶段输出、事件、加密配置均在 MySQL。一次分析最多使用 90000 个来源正文字符；超出明确报错要求缩小范围，不自动裁剪证据。未接入向量检索。
- COS 存原件和按页图像；切换设置只影响新文件。旧文件仍需原桶权限。本地开发文件在 `.local/files`。
- 原文、版本、施行日期变化分别保存版本，不把历史正文合并为“现行有效”。分析保存引用标识与正文快照。
- “已关联原文”“模型认为有支持”“法律效力待复核”分别记录。模型复核不等于人工审定。没有法规/案例原文时只输出研究方向和缺口，不声称完成全面检索。
- 单管理员账号与密码登录，由 `APP_USERNAME` 和 `APP_PASSWORD` 配置；不提供公开注册或多用户管理，案件仍属于同一工作空间。接口有会话认证、写请求头校验、文件类型检查和密钥加密。对外部署需 HTTPS、`COOKIE_SECURE=true`、访问控制和备份。
- 根 `.env` 的 `APP_SECRET` 用于加密配置。备份 MySQL 时同时安全备份此密钥；更换密钥会使旧配置无法解密。
- 取消在当前模型请求返回后生效，不回滚模型费用。Worker 每 15 秒心跳，定期将超过 5 分钟无心跳的任务标为中断。已完成阶段保留，但不自动从中间恢复；重新发起生成新任务。
- 不自动提交法院、发函、支付或对外沟通。外部请求限于配置的模型、COS、可选 MCP 和主动导入的官方网页。CrewAI 遥测和 tracing 默认关闭。

## 验证

```bash
python3 scripts/prepare_test_db.py
cd law_backend
uv run pytest -q
uv run ruff check src tests migrations
uv run alembic check
cd ../frontend
npm run build
```

测试默认使用独立的 `law_workspace_test`，也可设置 `LAW_TEST_DATABASE_URL`，库名必须以 `_test` 结尾。测试会清空测试库业务表，禁止指向真实案件库。

自动化覆盖真实 MySQL、真实 CrewAI Flow/Agent、文件解析、版本隔离、取消、SSE、加密配置和输出复核。云适配测试使用模拟 HTTP/SDK 响应，不能替代真实 DeepSeek、TokenHub、COS 或付费 MCP 联调。浏览器验收使用 `examples/合成测试素材.txt`，演示内容明确标记为合成。

## 代码入口

- `frontend/src/App.vue`：案件、素材、分析和来源预览。
- `frontend/src/SettingsView.vue`：供应商、COS、MCP 配置及连接测试。
- `law_backend/src/law_backend/api.py`：认证和业务 API。
- `law_backend/src/law_backend/worker.py`：任务领取、心跳、取消和执行。
- `law_backend/src/law_backend/main.py`：四阶段 CrewAI Flow。
- `law_backend/src/law_backend/llm.py`：CrewAI BaseLLM 适配器，使用 JSON 对象或普通文本输出并在本地做 Pydantic 校验，不强制供应商支持 OpenAI strict JSON Schema。
- `law_backend/src/law_backend/contracts.py`：结构化结果和引用/复核状态。
- `docs/技能包审查与架构建议.md`：原包审查证据与架构取舍。

官方依据：[CrewAI 文档索引](https://docs.crewai.com/llms.txt)、[CrewAI 自定义 LLM](https://docs.crewai.com/v1.15.22/en/learn/custom-llm)、[DeepSeek JSON Output](https://api-docs.deepseek.com/zh-cn/guides/json_mode/)、[DeepSeek API](https://api-docs.deepseek.com/zh-cn/)。
