"""账号注销的端口（`AccountDataPurger`）与五步编排（`delete_account`）——归属 `core/auth`。

边界：编排只依赖 `core/*` 与上游 SDK，不 import 任何 `modules/*`；会话撤销、身份用户删除
与各领域清除由装配处注入；第 1 步先写墓碑，五步顺序不可调换。

归属与参考（见 docs/项目结构设计.md 第 6 节）：设计真源是 [认证与账号] 第 8 节与决策记录
docs/技术设计/decisions/账号注销与墓碑.md，墓碑语义见本包 `tombstone.py`。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.auth.tombstone import DELETION_REASON_USER_REQUEST
from campfire.core.auth.tombstone_repository import record_deletion
from campfire.core.pending_write.models import STATE_PROCESSING, PendingWrite

logger = logging.getLogger(__name__)


class AccountDeletionError(Exception):
    """账号注销过程中的失败。

    任一步失败即整体失败并明确报错（第 8 节：不留「用户已删但数据仍可读」的
    中间态）。异常携带已完成到哪一步——步骤粒度到单个清除者（如
    `领域清除（memory）`），因为注销不可逆、操作者需要知道当前处于什么状态
    才能决定是重试还是人工介入；purger 之间互不知晓，报告里看不出
    「哪个领域已清过」就无法安全重试。
    """

    def __init__(self, step: str, detail: str, completed: tuple[str, ...] = ()) -> None:
        """记录失败步骤、原因与已完成的步骤。

        Args:
            step: 失败的步骤名。
            detail: 失败原因（不含凭据与用户内容）。
            completed: 失败前已成功完成的步骤名（按完成顺序）。
        """
        self.step = step
        self.detail = detail
        self.completed = completed
        done = "、".join(completed) if completed else "（无）"
        super().__init__(f"账号注销在「{step}」失败：{detail}；此前已完成：{done}")


@dataclass(frozen=True)
class PurgeOutcome:
    """一个 purger 的清除结果（如实报告做了什么）。"""

    #: 清除者的名字（用于日志与结果汇总，如 `"memory"`）。
    name: str
    #: 人类可读的说明（如「已丢弃账号图」或「无图可丢弃」）。
    detail: str


@runtime_checkable
class AccountDataPurger(Protocol):
    """账号数据清除者的端口。

    各业务模块（记忆、将来的档案）实现它，由装配处注入给 :func:`delete_account`。
    `core/auth` 只认识这个协议，不认识任何具体模块（依赖白名单）。

    实现者的契约：

    - 必须幂等：账号没有数据时返回「无数据可清」而不是报错——重试注销是正常路径
      （见 :func:`delete_account` 的幂等说明）。
    - 不得抛「账号不存在」类异常：那是正常情形，不是失败。
    - 失败必须抛出（而不是吞掉）：注销的语义是「内容真删」，
      静默失败会让「已删除」变成一句谎话。
    - 提供 `name` 属性（领域名，如 `"memory"`）：编排的步骤名与失败点名
      从它取——多个清除者并存时，操作者据此分辨「哪个领域已清过、哪个失败」。
      与 :class:`PurgeOutcome.name` 同源，勿与类名耦合。
    """

    #: 清除者的领域名。编排步骤名（`领域清除（<name>）`）与失败点名共用。
    name: str

    async def purge_account(self, account_id: str) -> PurgeOutcome:
        """清除该账号在本领域的全部数据。

        Args:
            account_id: 账号标识（身份服务的用户标识）。

        Returns:
            :class:`PurgeOutcome`，说明本次实际做了什么。

        Raises:
            Exception: 清除失败。不要吞——见上方契约。
        """
        ...  # pragma: no cover —— Protocol 抽象体，合法空体


@dataclass
class DeletionReport:
    """注销完成后的如实报告。"""

    account_id: str
    #: 已完成的步骤名（按完成顺序）。重试时可以看出哪些是本次新做的。
    completed_steps: list[str] = field(default_factory=list)
    #: 墓碑是本次新建，还是此前已存在（重试时为 `False`）。
    tombstone_created: bool = True
    #: 各 purger 的结果。
    purges: list[PurgeOutcome] = field(default_factory=list)
    #: 被删除的未领取待处理记录条数。
    pending_writes_deleted: int = 0


async def delete_account(
    session: AsyncSession,
    *,
    account_id: str,
    revoke_all_sessions: Callable[[str], Awaitable[None]],
    delete_identity_user: Callable[[str], Awaitable[None]],
    purgers: list[AccountDataPurger] | None = None,
    reason: str = DELETION_REASON_USER_REQUEST,
    confirmed: bool = False,
) -> DeletionReport:
    """执行账号注销的五步（第 8 节）。不可逆。

    为什么编排在 `core/auth` 而不是 `modules/accounts`：

    注销要删的东西横跨多个模块（身份、会话、记忆图、待处理记录、账本），而
    `modules/*` 之间禁止互相依赖（项目结构设计第 7 节）——没有任何单个业务模块
    能承担这条编排。因此：

    - 端口（:class:`AccountDataPurger`）与编排（:func:`delete_account`）落在
      `core/auth`：它只依赖 `core/*` 与上游 SDK，符合白名单；
    - 各模块提供自己的清除实现（`modules/memory` 的图清除等），在装配处注入
      ——与「工具注册在装配处完成」「注册复写在装配处注入」同一种做法；
    - `core/*` 不 import 任何 `modules/*`：编排只认识协议，不认识具体实现。

    这样新增一个需要清除的领域时，不改编排，只多提供一个 purger。

    五步顺序不可调换（第 1 步最先、删身份用户最后）：

    [认证与账号] 第 8 节要求领域清除早于删身份用户，五步按此落成：

    1. 先写墓碑——使在途记录立即失去写入资格；
    2. 删除该账号未领取的 `pending_write` 记录；
    3. 撤销该账号全部会话；
    4. 清除各领域数据（经 purger：档案条目、支持对象、会话‑对象绑定、会话归属行、
       记忆图与删除账本）；
    5. 删除身份服务的用户——最后一步。

    为什么领域清除必须早于删身份用户：

    第 8 节给的理由是「身份用户一旦删除，就再也无法按 `account_id` 定位这些行」。
    该理由在本实现里不成立：`account_id` 由调用方传入，各 purger 只认这个入参，
    从不回查身份服务（见 `cli/operator.py` 的注入处与各 purger 的签名）。顺序本身
    仍须遵守，收益是另一条与实现无关的排序纪律：删身份用户是本流程里唯一不可逆、
    且对外宣告「该账号不存在了」的动作，也就是整件事的提交点，必须排在所有可能
    失败的工作之后。排在前面会留下第 8 节要排除的残余状态：清除者随后失败时，
    账号已不可恢复地消失，而清除工作仍欠着——欠账的凭据只剩操作者屏幕上的一行
    报错，之后没有任何可判定的依据能说出「哪些账号的清除没做完」。

    已知代价（如实写明）：领域清除失败时身份用户仍在，账号的凭据未被删除——使用者
    仍能用密码登录（第 3 步已撤销会话，但登录会新建会话），从而看到被部分清除的
    数据。这是把「数据残留但不可读」换成了「数据可读但不一致」；两者都不是数据
    泄露，取舍取提交点靠后、失败可续做。

    为什么墓碑必须先写：注销时可能已有 `pending_write` 在排队、甚至已被 Worker
    领取。若账号删得无迹可寻，Worker 写入时查不到账号——而「查不到」与
    「账号从不存在」无法区分，于是数据被写回已注销账号的图（删后复活）。
    墓碑是 Worker 识别「已注销」的唯一依据（见 `tombstone.py`）。

    已知残余窗口（如实写明，不假装不存在）：

    第 1 步与第 4 步之间仍有极窄竞态：Worker 可能在「读墓碑（尚无）」之后、
    图被丢弃之前完成写入，从而重建该账号的图。

    后果有界：流程走完后该账号已不存在、无人能以其身份登录，读路径一律按登录态
    取数，因此重建的图此后不可经应用读取——属存储残留（`EVID-D`），不是数据
    泄露。唯一新增的可读片段在第 4 步与第 5 步之间：图已丢弃、身份用户尚在，
    此刻若 Worker 恰好重建该图，账号仍能登录把它读出来——窗口是一次删身份用户
    调用的时长。领域清除排在删身份用户之后时不存在这个片段（丢弃是最后一步，
    那时账号已经没了），它是本次顺序调整的代价，如实写明。

    彻底闭合需每账号锁或「注销前排空队列」，一期不做；已登记待实测。

    为什么外部操作是参数：

    「撤销全部会话」与「删除身份用户」属于身份服务的调用（SDK），而
    `core/auth` 允许依赖 SDK——但把它们做成参数可以让编排可测
    （用假实现验证顺序与失败语义，无需真实 core），也让编排只关心顺序与失败语义
    这一件它该负责的事。装配处（CLI）传入真实实现。

    幂等性：

    墓碑的写入是幂等的（`ON CONFLICT DO NOTHING`），因此重试是安全的：
    重跑会看到墓碑已存在（`tombstone_created=False`），继续完成后续步骤。
    这是必要的——第 2 步之后任一步失败都会留下部分完成的状态，而操作者
    唯一合理的动作就是修好原因后重试。

    为什么 `confirmed` 必须显式为真：

    第 8 节：注销不可逆，CLI 须要求显式确认。把这个检查放在编排层而不是
    只放在 CLI 参数解析里，是因为「有没有确认」是这次操作的语义的一部分，
    不该只由某个调用点的参数默认值表达。默认 `False` 意味着忘了传就拒绝执行，
    方向安全。

    Args:
        session: 关系库会话（墓碑与待处理记录的删除用；这两步各自立即提交，
            不依赖调用方的事务结局）。
        account_id: 要注销的账号标识。
        revoke_all_sessions: 撤销该账号全部会话的实现，签名 `(account_id: str) -> Awaitable[None]`。
        delete_identity_user: 删除身份服务用户的实现，签名同上。
        purgers: 各领域的清除者。为空表示没有需要额外清除的领域。
        reason: 注销原因（词表见 `tombstone.TOMBSTONE_REASONS`）。
        confirmed: 必须显式为真，否则拒绝执行（见上）。

    Returns:
        :class:`DeletionReport`。

    Raises:
        AccountDeletionError: 未确认，或任一步失败（携带已完成步骤）。
    """
    if not confirmed:
        raise AccountDeletionError(
            "确认",
            "未确认注销。注销不可逆，调用方必须显式传入 confirmed=True",
        )

    report = DeletionReport(account_id=account_id)
    completed: list[str] = []

    # --- 第 1 步：先写墓碑（必须最先，见模块说明）---
    #
    # 必须立即提交，不能等到最后（2026-09-30 实测修正，由
    # `test_tombstone_is_written_before_any_other_step` 抓到）：
    # 第 3、4、5 步调用的都是跨进程、不可回滚的外部操作（身份服务的会话与用户、
    # 图库）。若把它们与墓碑放在同一个未提交事务里，会出现两个问题：
    #
    # 1. 墓碑在提交前对 Worker 不可见——而第 8 节要求它「使在途记录立即失去
    #    写入资格」。「立即」指对其他事务立即生效，因此必须先提交。
    # 2. 更糟：外部删除成功之后若本事务回滚，账号与图都没了、墓碑也被回滚
    #    ——于是 Worker 完全无法区分「已注销」与「从不存」，正是墓碑要防的
    #    「删后复活」。这与注册侧「占用必须先独立提交」是同一条纪律。
    try:
        tombstone = await record_deletion(session, account_id=account_id, reason=reason)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise AccountDeletionError("写墓碑", f"{type(exc).__name__}: {exc}", tuple(completed)) from exc
    report.tombstone_created = tombstone.created
    completed.append("写墓碑")

    # --- 第 2 步：删除未领取的待处理记录 ---
    #
    # 只删未领取的（第 8 节原文）：`processing` 状态的记录可能正被 Worker
    # 持有并写入，删除它会让那次写入失去可追踪的记录——而墓碑已经保证它
    # 就算写也会被判定为「已注销」（Worker 读取时复查）。因此这里放过 processing，
    # 由 Worker 自己按墓碑丢弃。这也让「注销后排空」有了明确的语义边界。
    try:
        result = await session.execute(
            delete(PendingWrite).where(
                PendingWrite.account_id == account_id,
                PendingWrite.state != STATE_PROCESSING,
            )
        )
        # `CursorResult.rowcount` 才是受影响行数；`Result` 上没有该属性
        # （mypy 实测抓到）。`session.execute` 对 DML 返回的正是 `CursorResult`，
        # 但静态类型是 `Result`，故此处显式取属性并给出安全默认值。
        report.pending_writes_deleted = int(getattr(result, "rowcount", 0) or 0)
        # 立即提交（理由与第 1 步同源：效力不能挂在别人的事务结局上）：各 purger
        # 各自开事务独立提交（`modules/*/purge.py`），任一 purger 失败时调用方的
        # `session_scope` 会回滚。本步若留在那个事务里，这条删除会随回滚消失，而
        # `completed` 已经记上「删除待处理记录」——报告就会虚报一个并未发生的动作。
        # 提交之后本步不再取决于调用方的事务结局，报告才无条件为真。
        # 代价有界：未领取的记录被提前删掉，而墓碑已使该账号的写入失去资格，
        # 早删晚删不影响正确性。
        await session.commit()
    except Exception as exc:
        raise AccountDeletionError("删除待处理记录", f"{type(exc).__name__}: {exc}", tuple(completed)) from exc
    completed.append("删除待处理记录")

    # --- 第 3 步：撤销全部会话 ---
    try:
        await revoke_all_sessions(account_id)
    except Exception as exc:
        raise AccountDeletionError("撤销全部会话", f"{type(exc).__name__}: {exc}", tuple(completed)) from exc
    completed.append("撤销全部会话")

    # --- 第 4 步：各领域的清除者 ---
    #
    # 逐个完成即逐个记录（2026-10-01 审查修正，消融：`test_partial_purger_failure_reports_completed_purger`）：
    # 多个 purger 时第 N 个失败，前 N-1 个已真实执行但按旧写法不会出现在
    # `completed` 里——操作者据「失败重试安全」重跑时，无法从报告区分「哪个领域
    # 已清过」。purger 自身幂等（端口契约），重跑安全；这里把粒度做实，报告才与
    # 事实一致。名字取自清除者自报的 `PurgeOutcome.name` 所在实例而不是类名：
    # 同一实现类可以被实例化多次（或一个类内部区分多种领域），类名无法分辨
    # 「哪一个实例失败」——这正是本修正要回答的问题。取不到实例名时退回类名
    # （结构性满足 Protocol 的实现者没有 `name` 属性，如测试里的假件）。
    #
    # 必须早于第 5 步（删身份用户）：顺序说明见函数文档。
    for purger in purgers or []:
        name = getattr(purger, "name", None) or type(purger).__name__
        try:
            outcome = await purger.purge_account(account_id)
        except Exception as exc:
            raise AccountDeletionError(f"清除 {name}", f"{type(exc).__name__}: {exc}", tuple(completed)) from exc
        report.purges.append(outcome)
        completed.append(f"领域清除（{name}）")

    # --- 第 5 步：删除身份服务的用户 ---
    #
    # 必须最后（顺序说明见函数文档）：它是唯一不可逆、且对外宣告「该账号不存在了」
    # 的动作，即整件事的提交点。排在领域清除之前，会让「清除失败」留下一个账号
    # 已消失、清除仍欠着且无从判定的状态。
    try:
        await delete_identity_user(account_id)
    except Exception as exc:
        raise AccountDeletionError("删除身份用户", f"{type(exc).__name__}: {exc}", tuple(completed)) from exc
    completed.append("删除身份用户")

    # 第 1、2 步已各自提交；此后编排不再写入本会话，结束时的提交由 `session_scope`
    # 或调用方完成（`expire_on_commit=False`——`core/db` 的约定——保证提交后仍可读取
    # 返回值）。
    report.completed_steps = completed
    logger.info(
        "账号注销完成：标识=%s 墓碑新建=%s 待处理记录删除=%d 清除者=%d",
        account_id,
        report.tombstone_created,
        report.pending_writes_deleted,
        len(report.purges),
    )
    return report


__all__ = [
    "AccountDataPurger",
    "AccountDeletionError",
    "DeletionReport",
    "PurgeOutcome",
    "delete_account",
]
