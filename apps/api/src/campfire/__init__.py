"""篝火智答应用包（单应用、两个运行入口：``main`` 与 ``worker``）。

目录归属见 docs/项目结构设计.md 第 2 节：

- ``agent/``  —— 通用 Agent 基座，产品无关，不含任何领域术语
- ``surfaces/`` —— 面：产品入口与运行装配
- ``tools/``   —— 产品侧工具实现，注册进基座工具池
- ``modules/`` —— 业务数据与用例（``library`` 含资料与案例的检索链）
- ``core/``    —— 跨切能力：config、db、cache、auth、authz、jobs
"""
