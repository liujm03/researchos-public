# ResearchOS 独立安装架构

Next.js/React/TypeScript前端 → REST API → FastAPI业务服务 → Provider端口。
SQLAlchemy/Alembic管理PostgreSQL规范关系；附件使用StorageProvider，外部元数据和AI为可选适配器。
一份安装一位owner，cookie会话与CSRF、owner查询隔离、来源与hash、任务幂等/未知结果保护均保留。

主线：课题 → 官方文献链接 → 本人查阅/Zotero → 批准Skill精读 → Markdown笔记 →
灵感/任务书 → 无执行工具代码建议 → 私有版本 → 实验室服务器交接 → 结果/证据 → 英文稿件。
研究执行只属于实验室服务器，本机不运行科研模型、实验、评价、训练或仿真。

apps/web为前端，apps/api/app为业务/API/Provider，apps/api/alembic为迁移。
Docker提供独立postgres/api/web/worker；Windows本机有按需宿主与桌面启动入口。
AI/Zotero/GitHub不因启动平台而自动获得登录或授权。
当前配置的默认Skill/模板未配置，笔记根为./data/analytical-notes；无个人硬编码路径。
代码、数据库、配置和文件的恢复分别处理。具体实现以源码和API合同为准。
