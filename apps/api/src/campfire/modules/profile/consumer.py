"""`kind = profile_item` 的消费：把待处理记录写成档案条目。

职责：领取一条待处理记录，按当前授权重新判定，落成档案条目并置 `done`。
边界：投递与状态机在 `core/pending_write`；本模块只把自足载荷变成条目，
不回查业务用例、不依赖请求上下文（写入路径第 7 节的 Worker 边界）。
参考：docs/技术设计/technical-details/写入路径.md 第 4、6 节；
docs/技术设计/technical-details/个性化档案.md 第 7、8 节。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.auth.tombstone_repository import is_account_deleted
from campfire.core.authz import require_writable
from campfire.core.pending_write import (
    KIND_PROFILE_ITEM,
    ORIGINS,
    PendingWrite,
    mark_done,
    take_for_processing,
)
from campfire.modules.profile.errors import InferredCannotBeConfirmedError, ProfileDataError
from campfire.modules.profile.models import confirmation_on_entry
from campfire.modules.profile.repository import find_item_by_pending_id, insert_item

logger = logging.getLogger(__name__)

#: 载荷里必须存在的键（第 3 节：载荷自足，Worker 不回查业务用例）。
PAYLOAD_DOMAIN = "domain"
PAYLOAD_TOPIC = "topic"
PAYLOAD_DESCRIPTION = "description"

#: 载荷里的可选键。
PAYLOAD_CONTEXTS = "contexts"
PAYLOAD_MANIFESTATIONS = "manifestations"
PAYLOAD_HELPFUL_SUPPORT = "helpful_support"
PAYLOAD_UNHELPFUL_SUPPORT = "unhelpful_support"
PAYLOAD_PERSON_REPORT = "person_report"
PAYLOAD_PROBABLE_NEED = "probable_need"


@dataclass(frozen=True, slots=True)
class ProfileWriteResult:
    """一次消费的结果。

    `written` 为 False 表示本次没有领取到记录（已被他人领取、租约未到期、
    或已是终结态）——这不是错误，是并发下的正常结果，调用方跳过即可。

    `discarded` 为 True 表示领取到了但因账号已注销而删除该记录、不写条目
    （与记忆侧同一处置：墓碑先写，在途记录立即失去写入资格）。
    """

    pending_id: str
    written: bool
    item_id: str | None = None
    discarded: bool = False


async def write_from_pending(session: AsyncSession, *, pending_id: object, lease_owner: str) -> ProfileWriteResult:
    """领取并消费一条 `profile_item`（第 8 节的 `write_from_pending`）。

    流程严格按写入路径第 4 节：原子领取 → 复查账号是否已注销 → 复查授权
    → 查幂等键 → 写条目 → 置 `done`。

    幂等键是 `pending_id`（第 5 节：档案条目对 `pending_id` 建唯一约束）
    幂等由两处共同保证：存储层的唯一约束，以及领取前的显式查重。
    查重不是多余的——唯一约束会在重复写入时抛异常，而这里要的是
    安静地跳过并置 `done`（重放不是错误）。

    授权必须在领取时重新判定（第 6 节）
    记录排队期间授权可能已经变化：对象可能被归档、账号可能被注销。
    两者都不成立时不写入，并按第 6 节处置（转 `dead` 由调用方做）。

    为什么不做落层判定的「重新判定」
    落层在工具实现层硬卡（第 7 节：`origin` 属推断时不得写成 `confirmed`）。
    Worker 只消费显式载荷，因此这里沿用载荷里的 `origin` 与它推导出的确认状态，
    并再校验一次「推断不得是 confirmed」——载荷可能是历史版本或被手工构造的。

    可选键：缺键是「未提供」，形状非法是失败（2026-09-30，D-41）
    ------------------------------------------------------

    六个可选键（情境、表现、有效支持、无效支持、本人陈述、可能需求）形状不对时
    显式失败，与必填键同一处置；只有「键缺失或值为 `None`」才算未提供。
    放宽成「形状不对也按未提供处理」会把载荷里本该落库的内容静默丢掉，而记录仍被
    置 `done`——`done` 是「写入成功」的唯一表示（写入路径第 2 节），下游于是读到
    「已完成但内容缺失」的条目。判据见 `_optional_list` / `_optional_text`。

    Args:
        session: 关系库会话（调用方负责提交）。
        pending_id: 待处理记录标识。
        lease_owner: Worker 标识（租约栅栏用）。

    Returns:
        :class:`ProfileWriteResult`。

    Raises:
        ProfileDataError: 载荷缺必填键，或任一字段（含可选键）形状不合法。
            这类失败重试无用，由调用方转 `dead`。
        AuthorizationError: 对象已归档或不属于该账号（含已注销）。
            由调用方按第 6 节转 `dead` 并记原因。
        PendingWriteNotFoundError: 记录在领取后消失（极端并发）。
    """
    record = await take_for_processing(session, pending_id=pending_id, lease_owner=lease_owner)
    if record is None:
        return ProfileWriteResult(pending_id=str(pending_id), written=False)

    # --- 复查账号是否已注销（写入之前，不可省）---
    if await is_account_deleted(session, account_id=record.account_id):
        logger.info(
            "账号已注销，删除待处理记录（不写档案）：pending_id=%s 账号=%s",
            pending_id,
            record.account_id,
        )
        await session.execute(delete(PendingWrite).where(PendingWrite.id == record.id))
        return ProfileWriteResult(pending_id=str(pending_id), written=False, discarded=True)

    if record.kind != KIND_PROFILE_ITEM:
        raise ProfileDataError(
            f"本消费者只处理 {KIND_PROFILE_ITEM}，收到 {record.kind!r}",
            operation="write_from_pending",
            detail=f"kind={record.kind!r}",
        )

    # --- 授权在领取时重新判定（第 6 节）---
    # 归档对象与已换主的对象都在此被拒；不写入，由调用方转 dead。
    if record.support_object_id is None:
        # 存储层 CHECK 保证 `profile_item` 必有对象；这里是纵深防御——
        # 拿到 None 说明数据被旁路改过，明确失败而不是往 NULL 对象上写。
        raise ProfileDataError(
            "profile_item 载荷缺 support_object_id",
            operation="write_from_pending",
            detail=f"pending_id={record.id}",
        )
    await require_writable(record.account_id, record.support_object_id)

    # --- 幂等：先查该 pending 是否已写成条目（第 5 节）---
    existing = await find_item_by_pending_id(session, pending_id=record.id)
    if existing is not None:
        logger.info("该待处理记录已写成条目，跳过：pending_id=%s item=%s", pending_id, existing.item_id)
        # 已写过：清理租约并置 done（重放不是错误，也不是「本次写入」）。
        await mark_done(session, pending_id=pending_id, lease_owner=lease_owner)
        return ProfileWriteResult(pending_id=str(pending_id), written=False, item_id=str(existing.item_id))

    payload = record.payload or {}
    domain = payload.get(PAYLOAD_DOMAIN)
    topic = payload.get(PAYLOAD_TOPIC)
    description = payload.get(PAYLOAD_DESCRIPTION)
    missing = [
        name
        for name, value in ((PAYLOAD_DOMAIN, domain), (PAYLOAD_TOPIC, topic), (PAYLOAD_DESCRIPTION, description))
        if not value
    ]
    if missing:
        raise ProfileDataError(
            f"载荷缺必填键：{' '.join(sorted(missing))}",
            operation="write_from_pending",
            detail=f"pending_id={record.id} payload_keys={sorted(payload)}",
        )

    origin = record.origin
    if origin not in ORIGINS:
        raise ProfileDataError(
            f"origin 不在词表内：{origin!r}",
            operation="write_from_pending",
            detail=f"pending_id={record.id}",
        )
    # 再次硬卡「推断不得冒充事实」：载荷不可信，确认状态由 origin 推导，
    # 不接受载荷里的任何确认状态（那会让一条被构造的载荷把推断写成事实）。
    confirmation = confirmation_on_entry(origin)
    if payload.get("confirmation") == "confirmed" and confirmation != "confirmed":
        raise InferredCannotBeConfirmedError(
            f"生成方式 {origin!r} 不得写成 confirmed（推断不得冒充事实）",
            operation="write_from_pending",
            detail=f"pending_id={record.id}",
        )

    # 可选键先定性再写：形状非法与「未提供」分开（见 `_optional_list`）。
    contexts = _optional_list(payload, PAYLOAD_CONTEXTS, record.id)
    manifestations = _optional_list(payload, PAYLOAD_MANIFESTATIONS, record.id)
    helpful_support = _optional_list(payload, PAYLOAD_HELPFUL_SUPPORT, record.id)
    unhelpful_support = _optional_list(payload, PAYLOAD_UNHELPFUL_SUPPORT, record.id)
    person_report = _optional_text(payload, PAYLOAD_PERSON_REPORT, record.id)
    probable_need = _optional_text(payload, PAYLOAD_PROBABLE_NEED, record.id)

    item = await insert_item(
        session,
        support_object_id=record.support_object_id,
        domain=str(domain),
        topic=topic,
        description=description,
        origin=origin,
        confirmation=confirmation,
        source=dict(record.source or {}),
        contexts=contexts,
        manifestations=manifestations,
        helpful_support=helpful_support,
        unhelpful_support=unhelpful_support,
        person_report=person_report,
        probable_need=probable_need,
        pending_id=record.id,
    )
    # 置 done 与清理租约同一次更新；带租约栅栏（CORE-03）：写入可能超过租约时长，
    # 期间记录会被另一个 Worker 重领，先领取者的迟到 mark_done 不得抢先成功。
    await mark_done(session, pending_id=pending_id, lease_owner=lease_owner)
    return ProfileWriteResult(pending_id=str(pending_id), written=True, item_id=str(item.item_id))


def _optional_list(payload: dict, key: str, pending_id: object) -> list | None:
    """取载荷里的可选列表键：键缺失或值为 `None` → 「未提供」；形状不对 → 显式失败。

    为什么不把形状非法也算「未提供」（2026-09-30，D-41）：那会静默丢掉一段本该
    落库的内容，而条目随即被置 `done`，下游只看到「已完成但内容缺失」。同一份载荷里
    必填键形状不对会抛错，可选键因此同一处置（写入路径第 6 节：不得静默丢弃）。
    载荷按第 3 节是自足的，形状不对说明它被手工构造或来自旧版本——重试无用，
    由调用方转 `dead` 并告警。

    Raises:
        ProfileDataError: 键在而值不是列表。
    """
    raw = payload.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ProfileDataError(
            f"载荷的可选键形状非法：{key} 不是列表",
            operation="write_from_pending",
            detail=f"pending_id={pending_id} key={key} type={type(raw).__name__}",
        )
    return list(raw)


def _optional_text(payload: dict, key: str, pending_id: object) -> str | None:
    """取载荷里的可选文本键：键缺失、`None` 或空串 → 「未提供」；形状不对 → 显式失败。

    空串按「未提供」处理不是形状问题（类型是对的），与必填键的判据一致——它同样
    把空串当缺失。其余理由见 `_optional_list`。

    Raises:
        ProfileDataError: 键在而值不是字符串。
    """
    raw = payload.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ProfileDataError(
            f"载荷的可选键形状非法：{key} 不是字符串",
            operation="write_from_pending",
            detail=f"pending_id={pending_id} key={key} type={type(raw).__name__}",
        )
    return raw or None


def to_pending_uuid(raw: object) -> uuid.UUID:
    """把外部传入的 `pending_id` 解析成 UUID（CORE-04）。

    Raises:
        ProfileDataError: 不是合法 UUID 字符串。
    """
    if isinstance(raw, uuid.UUID):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise ProfileDataError(
            "pending_id 必须是非空字符串",
            operation="to_pending_uuid",
            detail=f"type={type(raw).__name__}",
        )
    try:
        return uuid.UUID(raw.strip())
    except ValueError as exc:
        raise ProfileDataError(
            "pending_id 不是合法 UUID",
            operation="to_pending_uuid",
            detail="无法解析为 UUID",
        ) from exc


# `AuthorizationError`（`require_writable` 抛出）不在此重导出：调用方从
# `core/authz` 取它，两处都导出同一个类型会让「错误类型的所有者是谁」变得模糊。
__all__ = [
    "PAYLOAD_CONTEXTS",
    "PAYLOAD_DESCRIPTION",
    "PAYLOAD_DOMAIN",
    "PAYLOAD_HELPFUL_SUPPORT",
    "PAYLOAD_MANIFESTATIONS",
    "PAYLOAD_PERSON_REPORT",
    "PAYLOAD_PROBABLE_NEED",
    "PAYLOAD_TOPIC",
    "PAYLOAD_UNHELPFUL_SUPPORT",
    "ProfileWriteResult",
    "to_pending_uuid",
    "write_from_pending",
]
