"""把三组适配器装起来：一个共享网关 + 各自的装配方式。

职责：按配置的组别集合构造适配器，并持有共享的 :class:`ModelGateway`。

边界：不跑批次、不写盘（那是 :mod:`evaluation.carebench.runner`）。

为什么共享一个网关：网关持有 HTTP 连接池与重试设置（见 `agent/model` 的模块说明）。
三组各建一个会让 A/B/C 的首字时延里混进三次 TLS 握手，而「时延」本身就是被报告的指标。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from campfire.agent.model import ModelGateway
from campfire.core.config import Settings

from ..config import RunConfig
from ..faults import FaultPlan
from .agent import AgentSystem
from .base import SystemAdapter
from .direct import DirectLLM
from .rag import RagBaseline


@dataclass
class AdapterBundle:
    """一次批次的适配器集合与共享网关。"""

    adapters: dict[str, SystemAdapter] = field(default_factory=dict)
    gateway: ModelGateway | None = None
    owns_gateway: bool = False

    async def aclose(self) -> None:
        """按组关闭适配器，再（若自建）关闭网关。"""
        for adapter in self.adapters.values():
            await adapter.aclose()
        if self.owns_gateway and self.gateway is not None:
            await self.gateway.aclose()
            self.gateway = None


def build_adapters(
    *,
    settings: Settings,
    config: RunConfig,
    faults: FaultPlan,
    gateway: ModelGateway | None = None,
) -> AdapterBundle:
    """构造配置里全部组别的适配器。

    Args:
        gateway: 测试缝——传一个脚本化网关即可让三组走完全相同的装配代码，
            只把外部模型供应商换掉（与产品 `composition.install(gateway=...)` 同一种做法）。

    Raises:
        ModelConfigurationError: 未配置凭据（真网关构造期）。
    """
    bundle = AdapterBundle()
    if gateway is None:
        gateway = ModelGateway(settings)
        bundle.owns_gateway = True
    bundle.gateway = gateway

    for system_id in config.systems:
        if system_id == "A":
            bundle.adapters["A"] = DirectLLM(settings=settings, config=config, gateway=gateway)
        elif system_id == "B":
            bundle.adapters["B"] = RagBaseline(settings=settings, config=config, gateway=gateway, faults=faults)
        elif system_id == "C":
            bundle.adapters["C"] = AgentSystem(settings=settings, config=config, gateway=gateway, faults=faults)
        else:  # pragma: no cover —— 配置校验已挡，保留兜底避免静默少跑一组
            raise ValueError(f"未知组别 {system_id!r}")
    return bundle


__all__ = ["AdapterBundle", "build_adapters"]
