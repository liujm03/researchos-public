# API和页面入口

API基址/api/v1；/health/ready提供基础就绪，开发模式/docs为OpenAPI文档（生产模式关闭）。
首次setup/login/logout与会话隔离在auth路由；写操作需owner会话与CSRF。
端点定义见apps/api/app/api/routes及生成前端合同apps/web/src/lib。

主要能力：dashboard、papers、research-notes、projects、ideas、tasks、codex任务、
integrations、服务器交接/结果、publications、exports、配置诊断。
API和页面中的具体字段以本版源码和OpenAPI为准，不复制他人现场任务或账户信息。

主页面：首页、文献、精读笔记、研究课题、科研灵感、AI任务、设置；更多工具按需使用。
文献/精读列表支持project_id/unclassified/collection_id；笔记分类通过独立GET/PUT维护，
与正文/审核分开。目录刷新仅元数据，默认不自动调用。
未配置的外部能力显示未配置/不可用，不使用假数据冒充服务成功。
