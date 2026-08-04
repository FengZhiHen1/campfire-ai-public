#!/usr/bin/env python3
"""Campfire-AI 统一种子注入脚本（ADR-013 重构版）。

本脚本为本地开发/内测环境提供唯一的数据初始化入口。
阶段 S1 起承担全库种子职责，后续阶段（S3 应急 / S4 档案 / S5 案例）随模块重构扩充。

当前注入范围（认证域）：
1. 六角色演示账号（family/volunteer/teacher/expert/admin/maintainer 各一，
   teacher/expert 直接落 active——演示已审核通过形态）
2. 演示邀请码（demand/supply 各两个，多次码便于内测分发）

用法:
    uv run scripts/seed.py              # 幂等注入全部种子数据
    uv run scripts/seed.py --clean      # 清空认证域数据后重新注入

设计约束:
- 完全幂等：按手机号/邀请码查重，重复运行不产生重复数据。
- 演示密码统一从环境变量 SEED_DEMO_PASSWORD 读取，缺省仅用于本地开发；
  生产/内测环境必须注入独立随机密码（安全规范：禁止硬编码密钥）。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 将项目根目录加入 PYTHONPATH，以便导入 workspace packages
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from py_auth.hashing import hash_password  # noqa: E402
from py_config import get_settings  # noqa: E402
from py_db.models.auth import Credential, InviteCode, User  # noqa: E402
from py_logger import logger  # noqa: E402
from py_schemas.auth import UserRole  # noqa: E402
from py_schemas.enums import AccountStatus, CredentialType, InviteChannel, InviteCodeStatus  # noqa: E402

# ---------------------------------------------------------------------------
# 演示账号配置（六角色各一）
# ---------------------------------------------------------------------------

# 演示密码：环境变量注入，缺省值仅限本地开发使用
_DEMO_PASSWORD: str = os.environ.get("SEED_DEMO_PASSWORD", "Campfire123")

# (角色, 手机号, 真实姓名, 落态)
_DEMO_USERS: list[tuple[UserRole, str, str, AccountStatus]] = [
    (UserRole.FAMILY, "13800000001", "演示家属", AccountStatus.ACTIVE),
    (UserRole.VOLUNTEER, "13800000002", "演示志愿者", AccountStatus.ACTIVE),
    (UserRole.TEACHER, "13800000003", "演示老师", AccountStatus.ACTIVE),
    (UserRole.EXPERT, "13800000004", "演示专家", AccountStatus.ACTIVE),
    (UserRole.ADMIN, "13800000005", "演示管理员", AccountStatus.ACTIVE),
    (UserRole.MAINTAINER, "13800000006", "演示维护员", AccountStatus.ACTIVE),
]

# 演示邀请码（固定码值便于内测分发；多次码）
_DEMO_INVITE_CODES: list[tuple[str, InviteChannel, int]] = [
    ("DEMAND26AA", InviteChannel.DEMAND, 10),
    ("DEMAND26AB", InviteChannel.DEMAND, 10),
    ("SUPPLY26AA", InviteChannel.SUPPLY, 5),
    ("SUPPLY26AB", InviteChannel.SUPPLY, 5),
]


async def seed_users(session) -> dict[str, User]:
    """注入六角色演示账号（幂等：按手机号查重）。

    Returns:
        phone → User 的映射（供邀请码 created_by 等关联使用）。
    """
    result = await session.execute(select(User))
    existing = {u.phone: u for u in result.scalars().all()}

    created = 0
    for role, phone, real_name, status in _DEMO_USERS:
        if phone in existing:
            continue
        user = User(phone=phone, real_name=real_name, role=role, status=status)
        session.add(user)
        await session.flush()

        credential = Credential(
            user_id=user.id,
            type=CredentialType.PASSWORD,
            identifier=phone,
            secret=hash_password(_DEMO_PASSWORD),
        )
        session.add(credential)
        existing[phone] = user
        created += 1

    await session.commit()
    logger.info(
        "seed",
        f"演示账号注入完成（新增 {created} / 共 {len(_DEMO_USERS)}）",
        op_type="seed",
    )
    return existing


async def seed_invite_codes(session, users_by_phone: dict[str, User]) -> None:
    """注入演示邀请码（幂等：按码值查重）。"""
    admin = users_by_phone.get("13800000005")
    if admin is None:
        raise RuntimeError("演示管理员账号缺失，无法关联邀请码 created_by")

    result = await session.execute(select(InviteCode))
    existing_codes = {c.code for c in result.scalars().all()}

    created = 0
    expires_at = datetime.now(timezone.utc) + timedelta(days=90)
    for code, channel, max_uses in _DEMO_INVITE_CODES:
        if code in existing_codes:
            continue
        session.add(
            InviteCode(
                code=code,
                channel=channel,
                max_uses=max_uses,
                used_count=0,
                expires_at=expires_at,
                status=InviteCodeStatus.ACTIVE,
                created_by=admin.id,
            )
        )
        created += 1

    await session.commit()
    logger.info(
        "seed",
        f"演示邀请码注入完成（新增 {created} / 共 {len(_DEMO_INVITE_CODES)}）",
        op_type="seed",
    )


async def clean_auth_domain(session) -> None:
    """清空认证域数据（--clean 模式）。"""
    from sqlalchemy import text

    await session.execute(text("TRUNCATE users, credentials, invite_codes CASCADE"))
    await session.commit()
    logger.info("seed", "认证域数据已清空", op_type="seed")


# ---------------------------------------------------------------------------
# 安全卡占位模板（D7：机制就绪、内容待专家撰写）
# ---------------------------------------------------------------------------

_UNIVERSAL_CARD = {
    "title": "通用安全卡",
    "template": (
        "【占位模板·待专家撰写】\n"
        "1. 移走周围可能的危险物品\n"
        "2. 降低环境刺激（关小声音、调暗灯光）\n"
        "3. 保持冷静，深呼吸\n"
        "4. 不要强行约束他\n"
        "5. 确保他在你的视线范围内"
    ),
}

# 各行为桶通用桶卡占位（桶 × 阶段变体按需生产，本期 meltdown 桶建全四阶段占位）
_BUCKET_CARD_TEMPLATES: dict[str, str] = {
    "情绪崩溃": "【占位模板·待专家撰写】情绪哭闹桶通用卡\n1. 保持安静陪伴\n2. 移走 {触发物}\n3. 递上 {安抚物}\n4. 用 {话术适配} 告诉他你在",
    "刻板行为": "【占位模板·待专家撰写】刻板升级桶通用卡\n1. 不打断，先观察\n2. 移走 {触发物}\n3. 提供替代感官活动",
    "自伤": "【占位模板·待专家撰写】自伤高危桶卡\n1. 立即用软垫挡住他撞击的部位\n2. 移走周围危险物品\n3. 保持近距离看护\n4. 如造成伤口，立即就医",
    "攻击": "【占位模板·待专家撰写】攻击高危桶卡\n1. 保护被攻击者，将其带离\n2. 保持距离，不正面阻拦\n3. 移走可用作攻击的物品",
    "走失": "【走失应急·占位模板·待专家撰写】\n立即报警话术：我的孩子{称呼}走失了。{体貌特征}。他是孤独症患者，可能没有危险意识。常去地点：{常去地点}。\n优先排查附近水体！",
    "用药相关": "【占位模板·待专家撰写】用药高危桶卡\n1. 保留药品包装\n2. 记录服用时间与剂量\n3. 立即联系主治医生或 120",
    "社交退缩": "【占位模板·待专家撰写】社交退缩桶通用卡\n1. 不强迫互动\n2. 提供安静的独处空间",
    "多动": "【占位模板·待专家撰写】多动桶通用卡\n1. 确保活动空间安全\n2. 移走易碎物品",
    "其他": "【占位模板·待专家撰写】通用桶卡\n1. 确保安全\n2. 保持冷静",
}

# meltdown 桶四阶段变体占位（高峰期只输出安全指令——机制 §3.1）
_MELTDOWN_STAGE_TEMPLATES: dict[str, str] = {
    "触发": "【占位模板·待专家撰写】情绪哭闹·触发期\n1. 移走 {触发物}\n2. 轻声叫他的名字{称呼}\n3. 递上 {安抚物}",
    "躁动": "【占位模板·待专家撰写】情绪哭闹·躁动期\n1. 减少语言，保持安静\n2. 陪伴在一侧，不对视压力",
    "加速": "【占位模板·待专家撰写】情绪哭闹·加速期\n1. 不讲道理，不说教\n2. 引导至安静区域",
    "高峰": "【占位模板·待专家撰写】情绪哭闹·高峰期\n1. 确保安全，移走危险物\n2. 保持距离看护\n3. 等待高峰过去",
}


async def seed_safety_cards(session) -> None:
    """注入安全卡占位模板（幂等：按 桶×阶段×标题 查重）。

    D7：占位模板标注「待专家撰写」，review_status=approved 以便供给链路就绪；
    真实内容生产另立排期（M3 审核链路）。
    """
    from py_db.models.consultation import SafetyCard
    from py_schemas.enums import BehaviorBucket, CrisisStage
    from py_schemas.enums.case_enums import CaseStatus

    result = await session.execute(select(SafetyCard))
    existing = {(c.bucket, c.crisis_stage) for c in result.scalars().all()}

    created = 0

    def _add(bucket, stage, title, template):
        nonlocal created
        if (bucket, stage) in existing:
            return
        session.add(
            SafetyCard(
                bucket=bucket,
                crisis_stage=stage,
                title=title,
                card_template=template,
                review_status=CaseStatus.APPROVED,
                version=1,
            )
        )
        created += 1

    # 通用卡（0 输入）
    _add(None, None, _UNIVERSAL_CARD["title"], _UNIVERSAL_CARD["template"])
    # 9 桶通用桶卡
    for bucket in BehaviorBucket:
        template = _BUCKET_CARD_TEMPLATES.get(bucket.value)
        if template:
            _add(bucket, None, f"{bucket.ui_label}·通用卡", template)
    # meltdown 桶四阶段变体
    for stage in CrisisStage:
        template = _MELTDOWN_STAGE_TEMPLATES.get(stage.value)
        if template:
            _add(BehaviorBucket.MELTDOWN, stage, f"情绪哭闹·{stage.value}期", template)

    await session.commit()
    logger.info("seed", f"安全卡占位模板注入完成（新增 {created}）", op_type="seed")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Campfire-AI 种子注入")
    parser.add_argument("--clean", action="store_true", help="清空认证域数据后重新注入")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_async_engine(str(settings.DATABASE_URL), echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        if args.clean:
            await clean_auth_domain(session)
        users = await seed_users(session)
        await seed_invite_codes(session, users)
        await seed_safety_cards(session)

    await engine.dispose()
    print("种子注入完成。演示账号：13800000001~13800000006（family/volunteer/teacher/expert/admin/maintainer）")
    print("演示邀请码：DEMAND26AA/DEMAND26AB（需求侧），SUPPLY26AA/SUPPLY26AB（供给侧）")


if __name__ == "__main__":
    asyncio.run(main())
