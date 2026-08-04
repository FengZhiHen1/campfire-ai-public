"""红线关键词词库加载。

加载策略：DB（redline_keywords 表）优先；表为空/加载失败回退内置默认词库
（冷启动与降级保障——词库迭代经运营后台，S7 前经 seed 注入）。

S5 统一说明：词库原语归 py-security 所有（阶段文档 T3.3），
本期在 crisis 模块内最小实现，S5 迁移时保持加载接口不变。
"""

from __future__ import annotations

from py_logger import logger
from sqlalchemy.ext.asyncio import AsyncSession

from py_db.repositories.redline_keyword_repository import RedlineKeywordRepository

# 内置默认词库（红线安全门 §3.2 示例词 + 机制兜底）：
# (关键词, 触发规则 ID)——规则 ID 供事件落库与词库迭代追溯
DEFAULT_KEYWORDS: list[tuple[str, str]] = [
    # 自伤
    ("撞墙", "KW_SELF_HARM_001"),
    ("撞头", "KW_SELF_HARM_002"),
    ("咬手", "KW_SELF_HARM_003"),
    ("抓破", "KW_SELF_HARM_004"),
    ("割腕", "KW_SELF_HARM_005"),
    ("打自己", "KW_SELF_HARM_006"),
    # 攻击
    ("打别人", "KW_AGGRESSION_001"),
    ("打人", "KW_AGGRESSION_002"),
    ("咬人", "KW_AGGRESSION_003"),
    ("抓人", "KW_AGGRESSION_004"),
    # 走失
    ("跑出去", "KW_ELOPEMENT_001"),
    ("走失", "KW_ELOPEMENT_002"),
    ("不见了", "KW_ELOPEMENT_003"),
    # 用药
    ("吃药", "KW_MEDICATION_001"),
    ("吞药", "KW_MEDICATION_002"),
    ("误服", "KW_MEDICATION_003"),
]


async def load_redline_keywords(session: AsyncSession) -> list[tuple[str, str]]:
    """加载红线词库：DB 优先，空表/异常回退内置默认（降级不阻断判定）。"""
    try:
        repo = RedlineKeywordRepository(session_factory=None)  # type: ignore[arg-type]
        rows = await repo.list_active(session)
        if rows:
            return [(row.keyword, row.trigger_rule_id) for row in rows]
        logger.info(
            service="api-server",
            message="redline_keywords_empty_using_default",
            extra={"default_count": len(DEFAULT_KEYWORDS)},
        )
    except Exception as exc:
        logger.warning(
            service="api-server",
            message="redline_keywords_load_failed_using_default",
            extra={"error": str(exc)},
        )
    return list(DEFAULT_KEYWORDS)


__all__ = ["load_redline_keywords", "DEFAULT_KEYWORDS"]
