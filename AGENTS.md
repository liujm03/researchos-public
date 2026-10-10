# ResearchOS 独立安装维护规则

- 每份安装只有一位所有者；所有查询、任务和产物按所有者隔离。
- 先读ARCHITECTURE.md、DATABASE.md、API.md、ROADMAP.md及AI_HANDOFF.md。
- 业务层使用Provider端口；浏览器不直接调用学术、AI、存储或账号服务。
- 不运行本地科研实验、模型、训练、评价或仿真；本地仅科研策划、资料管理和有界代码改进。
- 软件检查只用合成数据/FakeProvider，不为测试导入真实Zotero、阅读私人PDF或调用付费AI。
- 首次建号由接收者完成；不要预置用户、自动seed、拷贝他人的数据库或共享密钥。
- 同步、AI与外发默认关闭，实际论文/输入/Skill/模板/保存路径须经本安装所有者批准。
- 保留来源/版本/哈希与人工编辑；AI候选不等于科学事实，未知调用不自动重放。
- 每个科研项目独立目录/Git历史/私有仓库。首次绑定核实本人账号与仓库身份。
- 推送前检查权限、私有状态、精确清单，排除PDF、数据、权重、笔记、数据库、凭据与运行文件。
- 保存README/使用教程、AGENTS和AI_HANDOFF，记录实际commit/tag/清单；不强制推送或改公开权限。
- schema修改需Alembic升级检查，API/schema修改同步OpenAPI与TypeScript合同。
- 运行相关pytest/Ruff/mypy/TypeScript/ESLint/build检查；未做的验证必须说明。
- 数据备份与代码归档分别管理，恢复不能覆盖现有数据库或资料；不擅自删除资料。
