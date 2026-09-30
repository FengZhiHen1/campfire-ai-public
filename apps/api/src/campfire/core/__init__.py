"""跨切能力：config、db、cache、auth、authz、jobs。

归属见 docs/项目结构设计.md 第 2 节。依赖白名单（第 7 节）：`core/*` 只允许
依赖上游库与 `core/*` 内同级，禁止依赖 `agent/*`、`surfaces/*`、
`modules/*`。

`core/config` 是配置唯一入口，其它模块不得各自读取环境变量形成第二真相；
配置面无法用包结构表达，故此处以文字重申，并由工程检查断言。
"""
