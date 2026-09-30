"""健康检查的状态形状与汇总规则。

职责：为每项能力定义健康结论形状，并汇总成一次健康检查的结论。
边界：只定义形状与汇总，不自己探测；探测由各能力所有者提供、装配处接线。
参考：`docs/项目结构设计.md` 第 10 节。
"""

# 以下为该模块原有说明，逐字保留：
#
# 设计要求（见 docs/项目结构设计.md 第 10 节）：分别报告各项能力，
# 不用一个全绿接口表示所有能力安全。
#
# 本模块只定义形状与汇总，不自己探测——探测由各能力的所有者提供，
# 并在装配处（`campfire.main`）接线。这样做的原因是依赖白名单：
# `core/*` 不得依赖 `agent/*`（第 7 节），因此模型探测必须由装配处调用。

from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    """单项能力的可用状态。"""

    OK = "ok"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    """一项能力的健康结论。

    `detail` 供人排查，不得包含凭据：探针只回报异常类型与简短原因，
    不复述连接串。
    """

    name: str
    status: Status
    detail: str

    def as_dict(self) -> dict[str, str]:
        """转成可序列化的形状，供健康检查端点输出。"""
        return {"status": self.status.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class HealthReport:
    """一次健康检查的完整结论。"""

    components: tuple[ComponentHealth, ...]

    @property
    def is_ready(self) -> bool:
        """全部能力可用才算就绪。"""
        return all(item.status is Status.OK for item in self.components)

    @property
    def degraded(self) -> tuple[ComponentHealth, ...]:
        """不可用的能力，供告警与排查使用。"""
        return tuple(item for item in self.components if item.status is not Status.OK)

    def as_dict(self) -> dict[str, object]:
        """转成端点响应体：顶层就绪结论 + 每项能力各自的结论。"""
        return {
            "ready": self.is_ready,
            "components": {item.name: item.as_dict() for item in self.components},
        }
