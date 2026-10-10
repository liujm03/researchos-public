# 从零安装与日常使用

## A. 推荐：Docker基础平台

1. 把ZIP解压到独立目录，例如 `C:\ResearchOSBlank`。不要覆盖别人或自己的已有实例。
2. 安装自己的Docker Desktop/Compose，完成本人条款选择并启动Linux引擎。首次构建需要联网下载基础镜像与依赖。
3. 本机有Python3.12或更新兼容版时运行：

```powershell
python scripts/initialize_blank.py --mode compose
```

脚本从空白模板生成自己的随机数据库密码、会话密钥、CSRF密钥与首次初始化令牌；
写入本机`.env`，不打印密钥，已有`.env`拒绝覆盖。不注册账户、不启动服务或导入文献。
没有Python时，复制`.env.example`为`.env`，自行设置独立随机密钥和数据库连接；
不要使用示例密码或分享`.env`，并设置自己独立的COMPOSE_PROJECT_NAME。
默认Web3100、API8100，独立Compose项目名隔离数据卷。

4. 双击 `start_researchos.cmd`，或在解压目录执行：

```powershell
docker compose up -d --build
```

5. 检查API就绪后访问 **http://127.0.0.1:3100**。第一次建号，从自己本机`.env`
读取`INITIAL_SETUP_TOKEN`，填写自己的邮箱、用户名和密码。只允许这一位所有者；
数据库迁移只建立结构，未运行seed，首页和文献列表初始为空。
6. `.env`中的数据密码与平台登录密码不同；后续沿用原账户登录，不重复注册。

基本平台只绑定回环地址，不自动开放给局域网/互联网。Docker卷保存数据库，
`data/attachments`保存自己的文件。`docker compose down`保留卷；**不要使用`down -v`来排错**。
多套安装不要复用Compose项目名、端口或已有数据库。

## B. Windows本机部署：适合自己的Zotero和Codex账号

需要自己安装Python3.12、Node24、pnpm11.19.0，以及自己下载的PostgreSQL17便携程序。
解压PostgreSQL到`data/runtime/postgresql/pgsql`，确认bin目录有initdb/pg_ctl/createdb。
推荐ASCII安装目录`C:\ResearchOSBlank`，默认数据库端口55432以避开已有实例。

```powershell
python scripts/initialize_blank.py --mode local
python -m venv .venv
```

API安装在`apps/api`目录执行，使用根目录虚拟环境：

```powershell
cd apps/api
& ..\..\.venv\Scripts\python.exe -m pip install -e '.[dev,codex]'
cd ../..
pnpm install --frozen-lockfile
```

在根目录初始化自己全新的cluster（只在data/postgresql17不存在时执行），
`-W`提示输入的密码填写自己`.env`中生成的POSTGRES_PASSWORD，不在命令参数中放密码：

```powershell
& .\data\runtime\postgresql\pgsql\bin\initdb.exe -D .\data\postgresql17 -U researchos -W --auth=scram-sha-256
& .\data\runtime\postgresql\pgsql\bin\pg_ctl.exe -D .\data\postgresql17 -l .\data\postgres.log -o '-h 127.0.0.1 -p 55432' -w start
& .\data\runtime\postgresql\pgsql\bin\createdb.exe -h 127.0.0.1 -p 55432 -U researchos -W researchos
```

数据库角色researchos与应用登录用户不同；应用账号稍后在网页建立。
本机模式生成的DATABASE_URL已经匹配上述独立cluster/密码/端口，
`API_INTERNAL_URL=http://127.0.0.1:8100`。若自己调整连接，URL编码密码并同步端口，
只写本机配置，不放命令参数/聊天/Git。此启动健康诊断核验受本安装管理的cluster，
不把任意外部数据库监听当成已验证实例。
安装完成后双击启动入口，它调用既有按需宿主；迁移/检查/构建通过才打开浏览器。
普通启动复用构建，源码改变后停止平台再用`start_durable.ps1 -Rebuild`。
可以运行`powershell -File scripts/install_desktop_launcher.ps1`创建自己的桌面启动按钮。

## 接入自己的数据和AI

1. Zotero：在自己的Desktop启用本机API，设置`ZOTERO_MODE=local`；这是本机API部署方式。
   Docker里的`127.0.0.1`不是宿主Zotero；Docker基础版可使用自己只读Zotero Web API，
   设置`ZOTERO_MODE=web`、自己的库ID/类型/API key。配置保存在服务端`.env`。
2. 文献：在“文献 → Zotero文献库”本人触发读取；读取元数据不启动精读。
   列表显示已同步的库/完整目录；可主动刷新文件夹名称层级，不导入论文/PDF或调用AI。
   文献和精读笔记均可多选研究课题；已接受笔记支持课题/未分类筛选，原文件和审核状态不变。
   课题“关联论文”按Zotero板块（可含子目录）搜索、分页勾选关联，后续页同样可选，不限首100篇。
3. Codex：在执行平台worker的同一Windows账户下登录自己的Codex，安装匹配SDK与CLI。
   配置`AI_PROVIDER=codex`、`CODEX_PROVIDER=openai_codex_sdk`、实际可用模型及推理强度。
   基础Docker镜像不包含Codex登录、CLI或专业Skill，不宣称开箱即用精读。
4. 精读：自行安装兼容的`zotero-analytical-writer`，指定自己绝对路径的
   `ANALYTICAL_WRITER_SKILL_PATH`、`ANALYTICAL_NOTE_TEMPLATE_PATH`和`ANALYTICAL_NOTE_ROOT`。
   `templates/reading-note.md`是中性模板起点，可自行替换；确认Skill内部没有别人的硬编码路径。
   在页面预览实际来源/Skill/模板/保存位置，本人批准后运行。没有Skill时明确未配置。
5. 规划/写作：分别安装自己的专业Skill，设置对应根目录/启用开关；保存候选和采纳版本。
6. GitHub/Hugging Face：配置自己的API/主机登录、独立项目目录和私有仓库。
   空白版无原作者账号、仓库绑定或推送目的地。
7. 论文PDF构建：另行配置自己授权的模板和已验证文档编译镜像；本包没有私人模板/镜像身份。

## 出错和找回

- 连接拒绝：先运行启动入口，查看`check_researchos.cmd`及`data/run`日志。
- Docker模式：`docker compose ps`、`docker compose logs --tail 100 api web worker`；
  `docker compose up -d --build`恢复服务，不删除卷或重建账户。
- 本机模式：`restart_researchos.cmd`保留数据库恢复；未知进程/身份冲突应先查明。
- AI结果未知：查看同一任务回执，不重复模型调用。额度/登录问题由自己的账号处理。
- 定期备份自己的数据库与附件。代码Git版本不含数据、凭据和Skill缓存。
  `scripts/backup.py`/`restore.py`支持完整备份及新目标恢复，先读`--help`，
  一致性备份前暂停API和worker；恢复到新空库/新目录，不能覆盖旧资料。

源码测试：在`apps/api`安装dev依赖后运行`python -m pytest tests -q`；
前端`pnpm typecheck:web`、`pnpm lint:web`、`pnpm build:web`。
本包提供基础配置测试；原作者的私人验收记录和科研样例未包含。
