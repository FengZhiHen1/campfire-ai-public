"""产品侧工具实现，注册进基座的工具池。

职责：把 `modules/` 的能力包装成基座可调用的工具（检索资料、检索案例、读写档案、读写记忆…）。
边界：禁止 import `surfaces/*`，禁止绕过用例服务直接写表；工具是代码，skill 是内容。
参考：docs/项目结构设计.md 第 6、7 节；契约见 docs/技术设计/面/consult/tools/（待确认）。
"""

# 归属（见 docs/项目结构设计.md 第 6 节）：`tools/` 把 `modules/` 的能力包装成
# 基座可调用的工具（检索资料、检索案例、读写档案、读写记忆…）。
# 工具是代码，skill 是内容：skill 通过 `allowed-tools` 声明预授权，
# 通过指令说明何时与如何使用工具。
#
# 依赖白名单（第 7 节）：`tools/*` 允许依赖 `agent/tools`、`modules/*`、`core/*`；
# 禁止 import `surfaces/*`，禁止绕过用例服务直接写表。
# `agent/tools` 之所以在列：工具实现的就是基座的接口（`ToolHandler` 收 `ToolContext`、
# 返回 `ToolOutcome`）——不依赖基座的类型就不是基座的工具。只放行 `agent/tools`，
# 不放行整个 `campfire.agent`；反方向（`agent/*` 不得 import `tools/*`）不变。
#
# 一期工具清单（见 docs/技术设计/面/consult/tools/）：`read_profile_summary`、
# `read_profile_items`、`propose_profile_item`、`read_memory`、`write_memory`、
# `search_knowledge`、`search_cases`——契约待确认。
#
# 已实现：`memory.py`（`write_memory` / `read_memory`）。
# 记忆的删除与纠正不在这里（2026-09-30 裁决）：它们由记忆面的 HTTP 契约承载，
# 不是模型可见工具——见 docs/技术设计/decisions/记忆删除走用户确认入口.md。
