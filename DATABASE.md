# 空数据库初始化

通过Alembic升级到当前head建立结构，不执行seed、不复制原作者数据库。
首次初始化之前User表为空；接收者用自己随机INITIAL_SETUP_TOKEN注册第一位owner。
后续setup拒绝建立第二位所有者。

核心关系定义见apps/api/app/models.py与其拆分模型模块，迁移见apps/api/alembic/versions。
包括文献/作者/来源、规范研究实体、项目/问题/任务书、精读/来源/批准/回执、
灵感、任务、实验与模型/数据登记、稿件/章节/引用/证据、集成与任务等。
来源、版本和关联不以大量JSON替代实体；缓存/批准快照有界保存。

数据库升级需备份与实际运行检查。SQLite合成测试不能证明PostgreSQL运行行为。
当前head a09020261010含独立笔记课题分类/关联表，owner复合FK和版本保护；新空库不会预置分类。
Docker卷和data附件由接收者自己的安装保存，RELEASE_MANIFEST不包含科研数据。
