"""账号侧产品工具：`finish_onboarding`。

职责：把引导收束用例包装成基座可调用的工具（契约映射 + 登录态取键 + 失败码映射）。
边界：只做包装——状态机、幂等语义与「不代写 skipped」都在
`modules/accounts/onboarding_completion.py`，此处不重复实现。
参考：docs/技术设计/面/consult/tools/finish_onboarding.md；
docs/技术设计/technical-details/认证与账号.md 第 8 节（双通道）；
docs/技术设计/面/consult/HTTP与SSE契约.md 第 6 节（另一条通道的幂等语义）。

归属（T04 裁决 3）：契约第 4 节第 3 条写「工具实现归 `modules/accounts`（状态表所有者），
契约映射之外不写逻辑」。用例层因此落在 `modules/accounts/onboarding_completion.py`；
本文件是它的工具侧包装，与 library/memory/profile 工具同形——契约映射留在这里，
是因为「工具名 → 参数模型 → 错误码」是 `tools/` 的职责，而 `modules/` 不认识工具。

为什么不收 `account_id` 与 `state`（契约第 2 节）：

- 不收 `account_id`：键取登录态（`RQ-ACC-01`），与其余账号级工具同一条纪律。
- 不收 `state`：状态取值由工具定死为 `completed`，不给模型选择 `skipped` 的通道。
  两条通道互不代写（认证与账号第 8 节），而这个「互不代写」只有在参数模型里
  根本没有 `state` 字段时才是结构性保证——若做成参数再在 handler 里拒绝，
  就又回到了「可以构造出越界调用」的状态。
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from campfire.agent.tools import ToolContext, ToolFailure, ToolResult
from campfire.core.config import get_settings
from campfire.core.db import session_scope
from campfire.modules.accounts.onboarding_completion import SKIPPED_SECTIONS, complete_onboarding

logger = logging.getLogger(__name__)

#: 账号键（与其余工具各持一份的理由见 `tools/profile.py` 的模块说明：
#: `tools/` 白名单不放行兄弟工具模块互相 import）。
ACCOUNT_PAYLOAD_KEY = "account_id"


#: 段名词表。语义所有者是 `modules/accounts/onboarding_completion.SKIPPED_SECTIONS`
#: （三段由 skill 的引导流程拥有），这里是一份受机械守住的镜像。
#:
#: 为什么不能 `Literal[*tuple(sorted(SKIPPED_SECTIONS))]` 派生：`Literal` 只接受字面量
#: 表达式，该写法被 mypy 判 `valid-type`（`Final` 常量同样不行，实测 mypy 2.1.0），
#: 于是整个参数模型的取值域在静态上不可用。镜像的漂移由
#: `test_onboarding_tools.py` 的 `test_section_enum_mirrors_the_module_vocabulary_exactly`
#: 断言双向相等来守住：模块侧增删一段而这里没跟着改，用例即失败。
_SectionName = Literal["onboarding", "profile_seed", "memory_seed"]


class FinishOnboardingArgs(BaseModel):
    """`finish_onboarding` 的参数（契约第 2 节）。"""

    model_config = ConfigDict(extra="forbid")

    skipped_sections: Annotated[
        list[_SectionName],
        Field(
            default_factory=list,
            description="本次引导中被跳过的段名（onboarding / profile_seed / memory_seed）；仅作记录，不影响状态取值",
        ),
    ]


async def finish_onboarding(context: ToolContext, args: FinishOnboardingArgs) -> ToolResult | ToolFailure:
    """把该账号的引导状态置为 `completed`（契约第 1 节）——引导收束段的最后一步。

    契约真源：docs/技术设计/面/consult/tools/finish_onboarding.md

    三件事（其余全在用例层）：

    1. 登录态取键：`payload` 里没有账号就明确失败，不猜（`RQ-ACC-01`）。
    2. 记录被跳过的段名：写进一条结构化日志。契约第 2 节说这个参数「仅作记录，
       不影响状态取值」，而状态表里没有承载它的列（只有 `account_id` / `state` /
       `updated_at`，契约第 7 节说 DDL 归 `modules/accounts`，本批不改 schema）。
       因此「记录」的落点只能是日志，而不是凭空造一个没有读者的字段或擅自加列。
       这是 T04 的实现裁决，已作为未决问题上报（若产品需要「哪些段被跳过」可查询，
       需要一次表结构与列语义的裁决）。
    3. 幂等：重复调用成功返回当前状态（用例层实现，见 `complete_onboarding`）。

    词表落参数枚举（与 `emit_emergency_action_card` 同法）：契约第 2 节把段名列成三个
    具名值，落成 `Literal` 后模型编不出第四段——与「状态取值由工具定死」是同一种
    机械保证思路，只是作用在段名上。

    未激活 onboarding skill 时的拒绝不在本函数里（契约第 4 节第 1 条）：那一条由
    `ToolDispatcher` 按 `allowed-tools` 与激活集合判定，返回 `tool_not_available`。
    工具可见性不是安全边界，服务端照常拒绝越界——而那条边界在派发层，不在这里。
    本函数因此不做激活状态检查：在 handler 里再判一次会制造第二处判据，
    且 handler 拿到的 `activation_state` 与派发层的判定可能不同步。

    Returns:
        `ToolResult`：`{"state": "completed"}`，或此前已被 UI 跳过时的
        `{"state": "skipped"}`（用例层的幂等语义：不把使用者的显式跳过改写掉）。
        `ToolFailure`：缺账号，或状态表写入失败——不得回执 `completed`
        （契约第 5 节末行：失败后 UI 跳过入口仍是补救通道）。
    """
    payload = context.payload
    account: object | None = None
    if isinstance(payload, dict):
        account = payload.get(ACCOUNT_PAYLOAD_KEY)
    if not isinstance(account, str) or not account.strip():
        return ToolFailure(
            code="tool_failed",
            message=f"缺少登录账号（装配处应在 payload 里提供 {ACCOUNT_PAYLOAD_KEY!r}）——无法完成引导",
        )

    try:
        async with session_scope(get_settings()) as session:
            state = await complete_onboarding(session, account_id=account)
    except Exception as exc:  # noqa: BLE001 —— 写入失败必须明确失败，不回执 completed
        # 异常消息可能带连接串（AGENTS.md 安全条款），因此只回类型名。
        logger.warning("finish_onboarding 失败：%s", type(exc).__name__)
        return ToolFailure(
            code="tool_failed",
            message=(
                f"引导状态未能更新（{type(exc).__name__}）——本次引导没有被标记为完成。"
                "下次日常会话会再次注入引导；使用者也可以用界面上的跳过入口。"
            ),
        )

    if args.skipped_sections:
        # 记录跳过事实（不影响状态取值）。排序后记录：日志的可读性与比对不依赖调用顺序。
        logger.info(
            "引导收束：账号=%s 状态=%s 跳过的段=%s",
            account,
            state,
            ",".join(sorted(args.skipped_sections)),
        )

    return ToolResult(text=json.dumps({"state": state}, ensure_ascii=False))


__all__ = [
    "ACCOUNT_PAYLOAD_KEY",
    "SKIPPED_SECTIONS",
    "FinishOnboardingArgs",
    "finish_onboarding",
]
