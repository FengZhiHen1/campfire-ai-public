"""通用 Agent 基座：产品无关的 Agent 底座。

判定标准（见 docs/项目结构设计.md 第 3 节）：基座知道自己如何运行，
不知道自己被用在哪件事上。出现领域术语（咨询、档案、案例、支持对象…）
即位置错误。

依赖白名单（第 7 节）：`agent/*` 只允许依赖 `core/config` 与上游库；
禁止 import `modules/*`、`surfaces/*`、`tools/*`。

子模块：`runtime`（agent loop 与会话）、`skill_runtime`（开放标准 skill
机制）、`tools`（工具池与权限系统）、`context`（注入项组织与引用索引）、
`model`（模型网关与路由）、`observability`（追踪与评测钩子）。
"""
