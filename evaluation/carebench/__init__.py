"""CareBench 评测工具：把 01–04 号评测协议落成可执行的运行器。

职责：读冻结案例 → 按 A/B/C 三组真实调用 → 逐轮落原始输出与轨迹 → 盲化评审包 →
人工评分导入与校验 → 只按实测数据汇总 → 校验证据包完整。

边界（刻意不做的事，都有理由）：

- 不新造服务、不新造评测平台：只复用产品已有的模型网关、工具池、技能注册表、
  Agent 运行时与会话存储；SDK 与 SQLAlchemy 依赖沿用应用自身。
- 不产生任何「补全过的漂亮答案」：失败、拒答、超时原样落盘并进入分母。
- 不由 LLM 代填人工评分：`critical_failure` 与五维分数只能由人工 CSV 导入，
  `pending` / `needs_review` 永远不算通过。
- 不碰生产数据：所有运行必须落在独立的评测库（见 :mod:`evaluation.carebench.knowledge`
  的隔离守卫），合成账号按 case-group 现造。

参考：`evaluation/carebench/protocol/`（01–05 号协议快照）、`evaluation/carebench/README.md`。
"""

from campfire.core.config import apply_no_proxy_normalization

#: 进程级 `no_proxy` 规范化——**必须早于任何 httpx/openai 客户端构造**。
#:
#: 产品在 `main.py` / `worker.py` 的模块导入期各调一次（`core/config` 的
#: `apply_no_proxy_normalization` 写明这是「入口级时序保证」）。评测工具是**第三个**
#: 程序内入口，不经过那两个模块，因此必须自己调——否则在 no_proxy 含 `[::1]` 的宿主机上，
#: agents-sdk 的 tracing 导出器会在构造 `httpx2.Client` 时抛 `InvalidURL: Invalid port: ':1]'`，
#: 表现为「C 组 100 ms 内失败、连 run_failed 都发不出来」（实测，2026-10-29 本机）。
#:
#: 放在包导入期而不是 `main()` 里：`AgentRunner` 可能被任何入口使用（含测试与将来的 CLI），
#: 而「谁忘了调一次」正是这条陷阱历史上反复出现的形态。幂等，重复调用无副作用。
apply_no_proxy_normalization()

__all__ = ["__version__"]

#: 工具版本。协议版本（`0.1`）与量表版本（`0.1`）各自记在 manifest 里，两者不混。
__version__ = "0.1.0"
