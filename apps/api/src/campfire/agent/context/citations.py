"""引用索引：让每条「可引用依据」都能回指到业务条目。

依据 docs/技术设计/technical-details/通用基座.md 第 4 节：

- 每条注入消息在引用索引表里留一条对应记录（来源、时间、指向的业务标识），
  输出里的引用要靠它回指。
- 不变量：没有索引记录的注入消息不得成为「可引用依据」。

这条不变量靠形状而不是靠纪律来守：可引用的凭据通道只有 :class:`CitationRecorder`
一条——它每次产出之前都先写索引，因此「拿着凭据却没写索引」在结构上不可表示。

（精确说法：`CitationRecord` 类型本身仍可被直接构造——索引的读回实现必须能从行记录
重建它，那是合法且必需的能力。因此不变量保证的是「经 recorder 发出的凭据必然有索引记录」，
而不是「这个类型无法在别处被构造」；后者既做不到，也不该做。）

索引的持久化实现不在基座内：`agent/*` 只允许依赖 `core/config`
（docs/项目结构设计.md 第 7 节），而 `core/*` 反过来不得依赖 `agent/*`，
所以实现由装配处（`main.py` / `surfaces` 一侧）提供，基座只声明端口。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from .errors import CitationError


def _utc_now() -> datetime:
    """默认时钟：带时区的当前时间。注入时钟是为了让测试不依赖真实时间。"""
    return datetime.now(UTC)


def _new_citation_id() -> str:
    """默认标识工厂：不透明且不重复。业务含义由 `source` 与 `reference` 承载。"""
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class CitationRecord:
    """引用索引里的一条记录。

    本类型只应由 :class:`CitationRecorder` 构造；直接 new 出来的记录没有索引写入，
    违反第 4 节的不变量。
    """

    citation_id: str
    """引用标识：面向使用者的稳定回指键。"""

    run_id: str
    """产生这条引用的运行。`run_finished` 的引用清单按它取用。"""

    source: str
    """来源标识（例如某个检索通道或业务库的名字）。"""

    reference: str
    """指向的业务标识，权威在业务条目本身。"""

    recorded_at: datetime
    """记录时间（带时区）。"""

    summary: str | None = None
    """一句话摘要，供面展示；不影响回指。"""


@runtime_checkable
class CitationIndex(Protocol):
    """引用索引的持久化端口。

    实现必须让 `list_for_run` 读回 `add` 写入的全部记录；写入失败必须抛异常——
    「没写进去」不得被当作「写进去了」（技术栈设计第 5 节第 2 条）。

    超时语义（实现方必须遵守）：实现必须自带超时上界。超时是「结果未知」——记录可能
    已经写入，因此不得把超时当作「确定没写」后重试而不带幂等键；`CitationRecorder`
    每次生成新的 `citation_id`（见 :func:`_new_citation_id`），朴素重试会产生重复记录。
    要么让写入按 `citation_id` 幂等，要么在超时后按该标识核实。
    """

    async def add(self, record: CitationRecord) -> None:
        """写入一条引用记录。"""
        ...

    async def list_for_run(self, run_id: str) -> Sequence[CitationRecord]:
        """按运行读回引用记录，顺序为写入顺序。"""
        ...


class CitationRecorder:
    """本轮运行的引用写入端：记录一次，返回一次可引用凭据。

    `issued` 是本轮已发出的引用清单，供 `run_finished` 事件与运行记录使用；
    它只反映真正写进索引的那些记录。
    """

    def __init__(
        self,
        index: CitationIndex,
        *,
        run_id: str,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] = _new_citation_id,
    ) -> None:
        """绑定一个索引实现与本次运行标识。

        Raises:
            CitationError: `run_id` 为空——引用记录必须能按运行读回。
        """
        if not run_id:
            raise CitationError("run_id 不能为空：引用记录必须能按运行读回")
        self._index = index
        self._run_id = run_id
        self._clock = clock
        self._id_factory = id_factory
        self._issued: list[CitationRecord] = []

    @property
    def run_id(self) -> str:
        """本次运行的标识。"""
        return self._run_id

    @property
    def issued(self) -> tuple[CitationRecord, ...]:
        """本轮已写入索引的引用，按写入顺序。"""
        return tuple(self._issued)

    async def record(self, *, source: str, reference: str, summary: str | None = None) -> CitationRecord:
        """写索引并返回这条可引用凭据。

        Raises:
            CitationError: 来源或业务回指为空。
            Exception: 索引写入失败原样冒泡——不得降级为「无引用」继续运行，
                否则使用者会看到一条无法回指的依据。
        """
        if not source:
            raise CitationError("来源不能为空：引用必须说明它从哪来")
        if not reference:
            raise CitationError("业务回指不能为空：引用必须指向一个业务标识")

        record = CitationRecord(
            citation_id=self._id_factory(),
            run_id=self._run_id,
            source=source,
            reference=reference,
            recorded_at=self._clock(),
            summary=summary,
        )
        await self._index.add(record)
        self._issued.append(record)
        return record
