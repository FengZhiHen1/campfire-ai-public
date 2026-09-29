"""产品侧工具实现，注册进基座的工具池。

归属（见 docs/项目结构设计.md 第 6 节）：``tools/`` 把 ``modules/`` 的能力包装成
基座可调用的工具（检索资料、检索案例、读写档案、读写记忆…）。
**工具是代码，skill 是内容**：skill 通过 ``allowed-tools`` 声明预授权，
通过指令说明何时与如何使用工具。

依赖白名单（第 7 节）：``tools/*`` 允许依赖 ``modules/*``、``core/*``；
**禁止 import ``surfaces/*``，禁止绕过用例服务直接写表**。

一期工具清单（见 docs/技术设计/面/consult/tools/）：``read_profile_summary``、
``read_profile_items``、``propose_profile_item``、``read_memory``、``write_memory``、
``search_knowledge``、``search_cases``——契约待确认。

尚未实现：本包当前无代码。
"""
