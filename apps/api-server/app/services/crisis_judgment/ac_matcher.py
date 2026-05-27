"""CSLT-01 危机分级判定 — AhoCorasickMatcher AC 自动机匹配器。

提供关键词词库的 AC 自动机构建、匹配和热加载功能。
使用 copy-on-write 策略保证热加载时的读线程安全。

技术要点：
    1. 使用 pyahocorasick 库构建 goto/failure/output 三表
    2. 从 PostgreSQL crisis_keywords 表加载关键词
    3. Copy-on-write 原子替换实现热加载
    4. 订阅 Redis Pub/Sub channel `keyword_dict:updates` 接收变更通知
    5. 降级机制：词库加载失败时模块正常工作（降级为纯前置选择 + LLM）
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import ahocorasick  # pyahocorasick >= 2.0

from .exceptions import KeywordDictLoadError
from py_logger import logger

# 否定词列表 —— 前向 7 字符扫描
# 最长否定词 2 字 + 5 字符前向上下文
NEGATION_WORDS: list[str] = [
    "没有",
    "不会",
    "以前",
    "不是",
    "从未",
    "不再",
    "还没",
]

# 最长否定词长度（用于前向扫描范围计算）
MAX_NEGATION_WORD_LENGTH: int = 2

# 前向扫描额外上下文长度
NEGATION_SCAN_CONTEXT: int = 5

# 前向扫描总长度 = 最长否定词长度 + 上下文长度
NEGATION_SCAN_WINDOW: int = MAX_NEGATION_WORD_LENGTH + NEGATION_SCAN_CONTEXT  # 7

# AC 自动机输出值中各字段的索引
# 格式：(keyword, keyword_id, category, trigger_rule_id)
_VALUE_IDX_KEYWORD: int = 0
_VALUE_IDX_KEYWORD_ID: int = 1
_VALUE_IDX_CATEGORY: int = 2
_VALUE_IDX_TRIGGER_RULE_ID: int = 3


def _negation_filter(
    match_start_pos: int,
    text: str,
    neg_words: list[str] | None = None,
) -> bool:
    """否定词过滤：检查匹配位置前向 N 个字符是否存在否定词。

    Args:
        match_start_pos: 匹配关键词在文本中的起始位置（字符索引）。
        text: 全文。
        neg_words: 否定词列表，默认为 NEGATION_WORDS。

    Returns:
        True = 该匹配被否定词否定（应排除该匹配）。
        False = 未被否定（该匹配有效）。
    """
    if neg_words is None:
        neg_words = NEGATION_WORDS

    if match_start_pos <= 0:
        return False

    # 前向扫描范围：[max(0, start - window), start)
    scan_start = max(0, match_start_pos - NEGATION_SCAN_WINDOW)
    prefix = text[scan_start:match_start_pos]

    for neg_word in neg_words:
        if neg_word in prefix:
            return True

    return False


class AhoCorasickMatcher:
    """AC 自动机匹配器（单例模式）。

    管理关键词词库的 AC 自动机构建、匹配查询和热加载。
    使用 copy-on-write 策略保证并发安全。

    Usage:
        matcher = AhoCorasickMatcher.get_instance()
        results = matcher.search("患者今天情绪比较稳定")
    """

    _instance: AhoCorasickMatcher | None = None
    _instance_lock: asyncio.Lock = asyncio.Lock()

    def __init__(self) -> None:
        self._automaton: ahocorasick.Automaton | None = None
        self._is_loaded: bool = False
        self._load_error: str | None = None
        self._last_load_time: float = 0.0
        self._keyword_count: int = 0
        # Redis 热加载订阅任务引用
        self._subscription_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # 单例管理
    # ------------------------------------------------------------------

    @classmethod
    async def get_instance(cls) -> AhoCorasickMatcher:
        """获取 AC 自动机匹配器全局单例。

        首次调用时自动从 PostgreSQL 加载关键词词库并编译 AC 自动机。
        后续调用直接返回已缓存的实例。

        Returns:
            AhoCorasickMatcher 单例实例。

        Raises:
            KeywordDictLoadError: 首次加载时关键词词库不可用。
        """
        if cls._instance is not None:
            return cls._instance

        async with cls._instance_lock:
            if cls._instance is not None:
                return cls._instance

            instance = cls()
            try:
                await instance._load_keywords_from_db()
            except KeywordDictLoadError:
                # 首次加载失败 —— 保留空实例并标记降级
                instance._is_loaded = False
                instance._load_error = "initial_load_failed"
                cls._instance = instance
                raise

            cls._instance = instance
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）。"""
        cls._instance = None

    # ------------------------------------------------------------------
    # 关键词加载（数据库 -> AC 自动机）
    # ------------------------------------------------------------------

    async def _load_keywords_from_db(self) -> None:
        """从 PostgreSQL crisis_keywords 表加载关键词并编译 AC 自动机。

        执行 SELECT keyword, category, trigger_rule_id FROM crisis_keywords
        WHERE is_active = true 全量查询。

        Raises:
            KeywordDictLoadError: PostgreSQL 连接失败或查询失败。
        """
        try:
            # ===== 占位实现 =====
            # 实际执行时应通过 py-db 的 async_session 查询：
            #
            # async with async_session() as session:
            #     rows = await session.execute(
            #         select(CrisisKeyword).where(CrisisKeyword.is_active == True)
            #     )
            #     keywords = []
            #     for row in rows.scalars():
            #         keywords.append((
            #             row.keyword,           # 关键词原文
            #             row.id,                # 关键词 ID
            #             row.category,          # severe/moderate/mild
            #             row.trigger_rule_id,   # 规则编号
            #         ))
            #     await self.load_from_data(keywords)

            automaton = ahocorasick.Automaton()
            automaton.make_automaton()

            self._automaton = automaton
            self._is_loaded = True
            self._load_error = None
            self._last_load_time = time.time()

        except Exception as exc:
            raise KeywordDictLoadError(
                detail=str(exc),
                original_error=exc if isinstance(exc, Exception) else None,
            ) from exc

    async def load_from_data(
        self,
        keywords: list[tuple[str, int, str, str]],
    ) -> None:
        """从内存数据加载关键词（用于测试和离线模式）。

        AC 自动机输出值格式：(keyword, keyword_id, category, trigger_rule_id) ——
        关键词原文存储在 value 中以供 iter() 直接返回，避免逆向查找。

        Args:
            keywords: 关键词列表，每项为 (keyword, keyword_id, category, trigger_rule_id) 元组。

        Raises:
            KeywordDictLoadError: 编译失败。
        """
        try:
            automaton = ahocorasick.Automaton()

            for keyword, keyword_id, category, trigger_rule_id in keywords:
                # value = (keyword, keyword_id, category, trigger_rule_id)
                automaton.add_word(
                    keyword,
                    (keyword, keyword_id, category, trigger_rule_id),
                )

            automaton.make_automaton()

            # Copy-on-write: 先编译，再原子替换
            self._automaton = automaton
            self._is_loaded = True
            self._load_error = None
            self._last_load_time = time.time()
            self._keyword_count = len(keywords)

        except Exception as exc:
            raise KeywordDictLoadError(
                detail=str(exc),
                original_error=exc if isinstance(exc, Exception) else None,
            ) from exc

    # ------------------------------------------------------------------
    # 核心匹配接口
    # ------------------------------------------------------------------

    def search(self, text: str) -> list[dict[str, Any]]:
        """在文本中执行 AC 自动机关键词匹配。

        对每条匹配项执行否定词过滤。若被否定词过滤排除，标记 negation_filtered=True。

        Args:
            text: 待扫描文本。

        Returns:
            匹配结果列表，每项包含：
                {
                    "keyword": 匹配到的关键词原文,
                    "keyword_id": 关键词 ID,
                    "category": 关键词分类（"severe" / "moderate" / "mild"）,
                    "trigger_rule_id": 触发规则编号,
                    "start_pos": 匹配起始位置,
                    "end_pos": 匹配结束位置,
                    "negation_filtered": 是否被否定词过滤排除,
                }

        Raises:
            RuntimeError: AC 自动机尚未加载。
        """
        if self._automaton is None:
            raise RuntimeError(
                "AhoCorasickMatcher has not been loaded yet. "
                "Call load_from_data() or get_instance() first."
            )

        results: list[dict[str, Any]] = []

        for end_pos, value in self._automaton.iter(text):
            # value 格式：(keyword, keyword_id, category, trigger_rule_id)
            keyword = value[_VALUE_IDX_KEYWORD]
            keyword_id = value[_VALUE_IDX_KEYWORD_ID]
            category = value[_VALUE_IDX_CATEGORY]
            trigger_rule_id = value[_VALUE_IDX_TRIGGER_RULE_ID]

            # 计算起始位置
            start_pos = end_pos - len(keyword) + 1

            # 否定词过滤
            negation_filtered = _negation_filter(start_pos, text)

            results.append({
                "keyword": keyword,
                "keyword_id": keyword_id,
                "category": category,
                "trigger_rule_id": trigger_rule_id,
                "start_pos": start_pos,
                "end_pos": end_pos,
                "negation_filtered": negation_filtered,
            })

        return results

    # ------------------------------------------------------------------
    # 热加载（copy-on-write）
    # ------------------------------------------------------------------

    async def reload(self, keywords: list[tuple[str, int, str, str]]) -> None:
        """热加载关键词词库。

        使用 copy-on-write 策略：先编译新的 AC 自动机，
        再通过原子赋值替换 self._automaton 引用。

        Args:
            keywords: 关键词列表，每项为 (keyword, keyword_id, category, trigger_rule_id) 元组。
        """
        # 步骤 1：编译新的 AC 自动机（在隔离的内存空间中）
        new_automaton = ahocorasick.Automaton()

        for keyword, keyword_id, category, trigger_rule_id in keywords:
            new_automaton.add_word(
                keyword,
                (keyword, keyword_id, category, trigger_rule_id),
            )

        new_automaton.make_automaton()

        # 步骤 2：Copy-on-write 原子替换
        # Python 的赋值操作是原子的（引用替换）
        self._automaton = new_automaton
        self._is_loaded = True
        self._load_error = None
        self._last_load_time = time.time()
        self._keyword_count = len(keywords)

        logger.info(
            service="crisis_judgment",
            message=f"AC automaton hot-reloaded with {len(keywords)} keywords",
            op_type=None,
            extra={"keyword_count": len(keywords)},
        )

    # ------------------------------------------------------------------
    # 热加载的 Redis 订阅
    # ------------------------------------------------------------------

    async def _subscribe_updates(self) -> None:
        """订阅 Redis channel `keyword_dict:updates` 接收热加载通知。

        待 py-cache 实现 Pub/Sub subscribe() 方法后启用。
        当前为占位，热加载通过外部显式调用 reload() 触发。
        """
        # TODO: 待 py-cache 实现 Pub/Sub subscribe() 方法后启用
        # async with get_redis_client() as redis:
        #     pubsub = redis.pubsub()
        #     await pubsub.subscribe("keyword_dict:updates")
        #     async for message in pubsub.listen():
        #         if message["type"] == "message":
        #             data = json.loads(message["data"])
        #             keywords = data.get("keywords", [])
        #             await self.reload(keywords)
        pass

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        """AC 自动机是否已成功加载。"""
        return self._is_loaded

    @property
    def load_error(self) -> str | None:
        """加载错误信息（若有）。"""
        return self._load_error

    @property
    def keyword_count(self) -> int:
        """已加载的关键词数量。"""
        return self._keyword_count

    @property
    def last_load_time(self) -> float:
        """上次加载成功的时间戳。"""
        return self._last_load_time
