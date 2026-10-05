"""代理环境变量的规范化：薄转出层，实现已下沉到 `core/config`。

职责：把 `core/config` 的规范化实现转出给 `agent/model` 的消费者
（`gateway.py` / `probe.py`），保持既有 import 路径与名字不变。
边界：本模块**不再有实现**；只做名字转出（单一真源的要求，见下）。
参考：实现与完整论证在 `campfire.core.config` 的「进程环境的 no_proxy 规范化」一节。

为什么实现搬到了 `core/config`（2026-10-05，T18）：

这条缺陷的产品侧受害者是 `core/auth` 的 SuperTokens querier（它自己
`AsyncClient(timeout=30.0)`，未传 `trust_env=False`），**`core/*` 不得 import `agent/*`**
（docs/项目结构设计.md 第 7 节，机械检查见 `apps/api/tests/test_layer_boundaries.py`
的 `ALLOWED["core"]`）——因此实现放在 `agent/*` 里的那一刻，产品侧就无法复用它，
只能另写一份，而那会制造第二真源（本项目已因「同一事实两处定义」修过一次）。

放在 `core/config` 的额外好处是不必改层白名单：`agent/*` 的白名单里**本来就有**
`campfire.core.config`（第 7 节的表首行），因此 `agent/model` 照旧能复用同一份实现，
而设计与文档都不必改。

为什么这个文件还留着（而不是删掉让调用方直接 import core）：

`gateway.py` 与 `probe.py` 已经在用 `from .proxy_env import
normalized_no_proxy_environment`，测试（`test_agent_model.py`）也 import 了
`normalize_no_proxy`。留着它是一个**名字的稳定落点**，把「实现搬家」这件事限制在
一处，而不是散到三个文件的 import 行上。代价是一个只有转出的模块——刻意接受。

为什么这里仍然重导出 `normalized_no_proxy_environment`（构造窗口版）而**不是**
进程级那个：`agent/model` 的两处构造在**非装配路径**上也会发生（CLI、单元测试），
那时进程级规范化没跑过；保留构造窗口版是纵深，不替代装配处的进程级调用。
"""

from __future__ import annotations

from campfire.core.config import (
    PROXY_ENV_NAMES,
    normalize_no_proxy,
    normalized_no_proxy_environment,
)

__all__ = ["PROXY_ENV_NAMES", "normalize_no_proxy", "normalized_no_proxy_environment"]
