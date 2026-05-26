# 后端实现模式参考

本文档提供常见后端实现模式的编码参考。按抽象模式组织，不绑定具体框架。

## 目录

1. [原子功能点与组合模式](#原子功能点与组合模式)
2. [模型定义模式](#模型定义模式)
3. [状态机实现模式](#状态机实现模式)
4. [异常处理模式](#异常处理模式)
5. [重试与降级模式](#重试与降级模式)
6. [依赖注入模式](#依赖注入模式)
7. [测试组织模式](#测试组织模式)

---

## 原子功能点与组合模式

每个核心步骤实现为一个**高内聚、低耦合**的原子函数，然后通过管道模式组合。

**反模式**：单个 `detect_all()` 方法内联三个检测算法 + 聚合 + 排序 + 持久化（函数体臃肿，算法无法独立测试或复用）。

**正确模式**——原子函数 + 管道组合：

```python
# 每个检测器是高内聚的原子功能点——单一职责、显式输入输出、可独立测试
def detect_coordinate_conflicts(nodes: list[Node], threshold: float = 0.01) -> list[ConflictReport]:
    conflicts = []
    for a, b in pairwise(nodes):
        if distance(a.coord, b.coord) < threshold:
            conflicts.append(ConflictReport(
                type="coordinate", entity_a=a.id, entity_b=b.id,
                evidence=f"距离 {distance(a.coord, b.coord):.4f} < {threshold}",
            ))
    return conflicts


def detect_timeline_conflicts(events: list[TimelineEvent]) -> list[ConflictReport]:
    conflicts = []
    for a, b in pairwise(events):
        if a.start < b.end and b.start < a.end:
            conflicts.append(ConflictReport(
                type="timeline", entity_a=a.id, entity_b=b.id,
                evidence=f"时间重叠: [{a.start},{a.end}] vs [{b.start},{b.end}]",
            ))
    return conflicts


def detect_naming_conflicts(entities: list[NamedEntity]) -> list[ConflictReport]:
    conflicts = []
    seen: dict[str, str] = {}
    for e in entities:
        if e.name in seen:
            conflicts.append(ConflictReport(
                type="naming", entity_a=seen[e.name], entity_b=e.id,
                evidence=f"名称重复: {e.name}",
            ))
        else:
            seen[e.name] = e.id
    return conflicts


# 组合层——管道模式串联，薄层只做编排
def detect_all_conflicts(
    nodes: list[Node], events: list[TimelineEvent],
    entities: list[NamedEntity], threshold: float = 0.01,
) -> list[ConflictReport]:
    results: list[ConflictReport] = []
    results.extend(detect_coordinate_conflicts(nodes, threshold))
    results.extend(detect_timeline_conflicts(events))
    results.extend(detect_naming_conflicts(entities))
    return sorted(results, key=lambda r: r.confidence, reverse=True)
```

### 组合模式选择

| 场景 | 推荐模式 | 说明 |
|:---|:---|:---|
| 步骤有明确顺序依赖（A→B→C） | **管道** | `step3(step2(step1(input)))` |
| 策略可替换（如不同算法） | **策略** | 定义 Protocol，注入具体策略实例 |
| 横切关注点（日志/重试/审计） | **装饰器** | `@retry @audit def atomic_fn(...)` |
| 一对多通知（事件广播） | **观察者** | 原子功能点发布事件，监听者响应 |
| 步骤可选、可配置 | **责任链** | 每步判断是否处理，传递给下一步 |

### 原子功能点检验标准

- [ ] **单一职责**：能否用一句话描述它做什么（不能说"做A和B还有C"）
- [ ] **显式输入**：所有输入在参数中，不读取全局状态
- [ ] **显式输出**：通过返回值传递结果，不修改入参
- [ ] **独立可测**：不启动整个应用就能为它写单元测试
- [ ] **无副作用**：不写数据库、不发网络请求（IO 留给组合层）
- [ ] **完整可用**：脱离主流程单独调用也能返回有意义的结果

---

## 模型定义模式

设计文档中的输入/输出代码块通常可直接转为 Pydantic 模型：

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional
from enum import Enum


class SeverityLevel(str, Enum):
    """严重级别枚举——从设计文档提取。"""
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ConflictReport(BaseModel):
    """单条冲突报告——对应设计文档输出定义。"""
    conflict_id: str = Field(description="唯一标识")
    severity: SeverityLevel = Field(description="严重级别")
    cypher_evidence: str = Field(default="", description="审计证据")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
```

**注意**：
- 设计文档中的 `Field(pattern=r"...")` 需保留为正则校验
- 若设计文档使用 `dataclass(frozen=True)`，优先使用 dataclass
- 枚举值必须与设计文档完全一致，不可自行增删
- 非 Python 替代：TypeScript → Interface + Zod，Go → Struct + tag，Rust → Struct + derive(Validate)

---

## 状态机实现模式

### 模式 A：显式状态类（复杂状态机）

```python
from enum import Enum, auto
from typing import Callable, Optional
from dataclasses import dataclass


class State(Enum):
    IDLE = auto()
    SCANNING = auto()
    COMPLETED = auto()
    BLOCKED = auto()


class Event(Enum):
    START_DETECTION = auto()
    SCAN_COMPLETE = auto()
    ANALYSIS_COMPLETE = auto()
    ERROR_FOUND = auto()


@dataclass(frozen=True)
class Transition:
    current: State
    event: Event
    next_state: State
    precondition: Optional[Callable] = None
    side_effect: Optional[Callable] = None


class StateMachine:
    """从设计文档状态机表格直接映射。"""

    TRANSITIONS: list[Transition] = [
        Transition(State.IDLE, Event.START_DETECTION, State.SCANNING),
        Transition(State.SCANNING, Event.SCAN_COMPLETE, State.COMPLETED),
    ]

    def __init__(self):
        self._state = State.IDLE

    def trigger(self, event: Event, context: dict) -> State:
        for tx in self.TRANSITIONS:
            if tx.current == self._state and tx.event == event:
                if tx.precondition and not tx.precondition(context):
                    raise ValueError(f"Precondition failed for {event}")
                self._state = tx.next_state
                if tx.side_effect:
                    tx.side_effect(context)
                return self._state
        raise ValueError(f"Invalid transition: {self._state} + {event}")
```

### 模式 B：字典驱动（简单状态机）

```python
TRANSITION_MAP = {
    ("IDLE", "start_detection"): ("SCANNING", None),
    ("SCANNING", "scan_complete"): ("COMPLETED", None),
    ("COMPLETED", "error_conflicts_exist"): ("BLOCKED", None),
}


def transition(current: str, event: str) -> str:
    key = (current, event)
    if key not in TRANSITION_MAP:
        raise ValueError(f"Invalid transition: {current} -> {event}")
    next_state, side_effect = TRANSITION_MAP[key]
    return next_state
```

---

## 异常处理模式

设计文档中每个"异常 N"条目应转化为明确的处理分支：

```python
from typing import Optional
from dataclasses import dataclass


@dataclass
class ExceptionSpec:
    """从设计文档提取的异常规格。"""
    name: str
    trigger_condition: str
    strategy: str
    retry_count: int
    retry_backoff: str  # "exponential", "fixed", "none"


def handle_exception_spec(spec: ExceptionSpec, context: dict) -> dict:
    logger.warning(
        f"Exception {spec.name} triggered: {spec.trigger_condition}", extra=context,
    )

    if spec.retry_count > 0 and spec.retry_backoff != "none":
        for attempt in range(spec.retry_count):
            try:
                result = retry_operation(context, attempt, spec.retry_backoff)
                return {"status": "recovered", "result": result}
            except Exception:
                if attempt == spec.retry_count - 1:
                    break

    return apply_degradation(spec.strategy, context)
```

**原则**：每个异常至少一条日志（级别按严重程度）；重试参数与设计文档完全一致；降级策略明确，不静默忽略。

---

## 重试与降级模式

### 指数退避

```python
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def with_exponential_backoff(
    fn: Callable[[], T], max_retries: int,
    base_delay: float = 1.0, max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
) -> T:
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except exceptions as e:
            if attempt == max_retries:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            time.sleep(delay)
```

### 安全降级

```python
@dataclass
class DegradedResult:
    data: Optional[dict]
    degraded: bool = False
    reason: Optional[str] = None


def safe_execute(fn: Callable, fallback: Callable, context: dict) -> DegradedResult:
    try:
        return DegradedResult(data=fn(context))
    except Exception as e:
        return DegradedResult(data=fallback(context), degraded=True, reason=str(e))
```

---

## 依赖注入模式

设计文档中的"依赖与集成接口"表格适合用依赖注入：

```python
class MyService:
    def __init__(self, graph_client, llm_client, calculator, logger=None):
        self._graph = graph_client
        self._llm = llm_client
        self._calc = calculator
        self._logger = logger or getLogger(__name__)
```

若依赖是具体实现，考虑提取接口：

```python
from typing import Protocol

class GraphClient(Protocol):
    def query(self, cypher: str, params: dict) -> list[dict]: ...
    def upsert_node(self, label: str, node_id: str, props: dict) -> None: ...
```

---

## 测试组织模式

### 按验收测试场景组织

```python
import pytest


class TestConflictDetection:
    """对应设计文档'验收测试场景'。"""

    def test_detect_coordinate_conflict(self):
        """Given: ... When: ... Then: ..."""
        pass

    def test_detect_timeline_conflict(self):
        """Given: ... When: ... Then: ..."""
        pass

    def test_empty_project_no_conflict(self):
        """Given: ... When: ... Then: ..."""
        pass

    def test_neo4j_timeout_degradation(self):
        """Given: ... When: ... Then: ..."""
        pass
```

### 命名约定

- 类名：`Test{模块名}`
- 方法名：`test_{场景描述}`（小写，下划线分隔）
- docstring：复制设计文档的 Given/When/Then

---

## 实现优先级速查

| 设计文档内容 | 优先级 | 典型位置 | 原子性要求 |
|:---|:---|:---|:---|
| 枚举/常量 | P0（最先） | `enums.py`, `constants.py` | 零依赖 |
| 输入/输出模型 | P0 | `schemas.py`, `models.py` | 只依赖类型系统 |
| 原子功能函数 | P1 | `services/xxx.py` | **高内聚、可独立测试** |
| 组合/编排层 | P1 | `orchestrator.py` | 薄层，只做串联 |
| 状态机 | P1 | `state_machine.py` | 独立模块 |
| 异常处理 | P2 | 装饰器或 `exceptions.py` | 装饰器形式附加 |
| 依赖接口 | P2 | 构造函数注入 | 面向接口 |
| 验收测试 | P3 | `tests/test_*.py` | 每个原子功能点独立 |
| 日志/审计 | P3 | 装饰器或内联 | 横切关注点 |
