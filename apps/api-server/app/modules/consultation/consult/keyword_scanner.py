"""CSLT-05 置信度后校验 — AC 自动机关键词扫描器。

封装 CSLT-01 的 AhoCorasickMatcher，为 CSLT-05 提供统一的
高危关键词扫描接口。使用 AC 自动机单例，与 CSLT-01/SEC-02
共享同一套关键词词库，确保三方关键词集合永远一致。

特性：
- 模块级单例 KeywordScanner
- 代理 AhoCorasickMatcher.search() 提供 scan_keywords()
- AC 自动机加载失败时降级为正则逐词扫描
- 支持 Redis Pub/Sub 热更新（代理 matcher.reload()）
- Copy-on-write 原子替换保证并发安全
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from py_logger import logger

from app.modules.crisis.ac_matcher import AhoCorasickMatcher
from app.modules.crisis.exceptions import KeywordDictLoadError

# ===========================================================================
# 降级关键词列表（AC 自动机加载失败时使用）
# ===========================================================================

FALLBACK_KEYWORDS: list[str] = [
    "自伤",
    "自杀",
    "药物",
]

# ===========================================================================
# 模块级事件标志
# ===========================================================================

_service: str = "consult.confidence"


class KeywordScanner:
    """AC 自动机关键词扫描器（单例模式）。

    封装 CSLT-01 的 AhoCorasickMatcher，为 CSLT-05 提供统一的
    关键词扫描入口。在 AC 自动机不可用时自动降级为正则逐词扫描。

    Usage:
        scanner = KeywordScanner.get_instance()
        hits = scanner.scan_keywords("建议服用药物以控制情绪")
        if hits:
            print(f"命中高危词: {[h['keyword'] for h in hits]}")
    """

    _instance: KeywordScanner | None = None
    _instance_lock: asyncio.Lock = asyncio.Lock()

    def __init__(self) -> None:
        self._matcher: AhoCorasickMatcher | None = None
        self._fallback_active: bool = False
        self._fallback_pattern: re.Pattern[str] | None = None
        # Compile fallback regex once
        _escaped = [re.escape(kw) for kw in FALLBACK_KEYWORDS]
        self._fallback_pattern = re.compile(
            "|".join(_escaped),
            re.IGNORECASE,
        )

    # ------------------------------------------------------------------
    # 单例管理
    # ------------------------------------------------------------------

    @classmethod
    async def get_instance(cls) -> KeywordScanner:
        """获取 KeywordScanner 全局单例。

        首次调用时初始化 AC 自动机实例。
        后续调用直接返回已缓存的实例。

        Returns:
            KeywordScanner 单例实例。
        """
        if cls._instance is not None:
            return cls._instance

        async with cls._instance_lock:
            if cls._instance is not None:
                return cls._instance

            instance = cls()
            try:
                instance._matcher = await AhoCorasickMatcher.get_instance()
                instance._fallback_active = False
            except KeywordDictLoadError:
                logger.warning(
                    service=_service,
                    message="AC automaton init failed, activating fallback keyword list",
                    extra={
                        "fallback_keywords": FALLBACK_KEYWORDS,
                    },
                )
                instance._fallback_active = True

            cls._instance = instance
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）。"""
        cls._instance = None

    # ------------------------------------------------------------------
    # 核心扫描接口
    # ------------------------------------------------------------------

    def scan_keywords(self, text: str) -> list[dict[str, Any]]:
        """在文本中执行关键词扫描。

        优先使用 AC 自动机（O(n) 复杂度），不可用时降级为正则逐词扫描。

        Args:
            text: 待扫描文本。

        Returns:
            匹配结果列表，每项包含：
                {
                    "keyword": 匹配到的关键词原文,
                    "keyword_id": 关键词 ID,
                    "category": 关键词分类,
                    "trigger_rule_id": 触发规则编号,
                    "start_pos": 匹配起始位置,
                    "end_pos": 匹配结束位置,
                    "negation_filtered": 是否被否定词过滤,
                }
            无命中时返回空列表。

        Raises:
            RuntimeError: 扫描器尚未初始化（应调用 get_instance() 后再用）。
        """
        if self._matcher is not None and not self._fallback_active:
            try:
                return self._matcher.search(text)
            except RuntimeError:
                logger.warning(
                    service=_service,
                    message="AC automaton search failed, falling back to regex",
                )
                return self._fallback_scan(text)

        return self._fallback_scan(text)

    def _fallback_scan(self, text: str) -> list[dict[str, Any]]:
        """降级正则逐词扫描。

        对 FALLBACK_KEYWORDS 中的每个词执行 re.search，
        返回与 AC 自动机兼容的结果格式。

        Args:
            text: 待扫描文本。

        Returns:
            匹配结果列表（与 scan_keywords 格式一致）。
        """
        if not self._fallback_pattern:
            return []

        results: list[dict[str, Any]] = []
        for match in self._fallback_pattern.finditer(text):
            keyword = match.group()
            results.append(
                {
                    "keyword": keyword,
                    "keyword_id": -1,
                    "category": "severe",
                    "trigger_rule_id": "KW_FALLBACK",
                    "start_pos": match.start(),
                    "end_pos": match.end(),
                    "negation_filtered": False,
                }
            )

        return results

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        """AC 自动机是否已成功加载。"""
        if self._matcher is not None and not self._fallback_active:
            return self._matcher.is_loaded
        return self._fallback_active

    @property
    def fallback_active(self) -> bool:
        """是否正在使用降级模式。"""
        return self._fallback_active

    @property
    def keyword_count(self) -> int:
        """已加载的关键词数量（降级模式下为 FALLBACK_KEYWORDS 长度）。"""
        if self._matcher is not None and not self._fallback_active:
            return self._matcher.keyword_count
        return len(FALLBACK_KEYWORDS)

    # ------------------------------------------------------------------
    # 热加载（代理 matcher.reload()）
    # ------------------------------------------------------------------

    async def reload_keywords(
        self,
        keywords: list[tuple[str, str, str, str]],
    ) -> None:
        """热加载关键词词库。

        代理 AhoCorasickMatcher.reload() 实现词库热更新。
        使用 copy-on-write 策略保证并发安全。

        Args:
            keywords: 关键词列表，每项为
                (keyword, keyword_id, category, trigger_rule_id) 元组。
        """
        if self._matcher is not None:
            await self._matcher.reload(keywords)
            self._fallback_active = False
            logger.info(
                service=_service,
                message=f"Keyword scanner hot-reloaded with {len(keywords)} keywords",
                extra={"keyword_count": len(keywords)},
            )


__all__ = [
    "KeywordScanner",
    "FALLBACK_KEYWORDS",
]
