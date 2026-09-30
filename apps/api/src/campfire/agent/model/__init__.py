"""模型网关与路由：模型名在代码中的唯一出现处。

归属（见 docs/项目结构设计.md 第 10 节）：模型名唯一出现处；业务代码不得硬编码
模型名。取值来自 `core/config`，依赖方向 `agent → core/config` 在第 7 节
白名单内。基座不含领域术语，本模块同样不含。

供应商约束（见 docs/技术栈设计.md 第 3 节）：腾讯云 TokenHub 是外部数据处理方。
`EVID-C` 未关闭前只发送虚构或经核准不可识别的样例（`RQ-LIM-03`）。

模块分工：:mod:`~campfire.agent.model.gateway` 是真实调用侧（客户端、重试预算、
用途分档），:mod:`~campfire.agent.model.probe` 是健康探针，:mod:`~campfire.agent.model.errors`
是失败分类。上界只有一条，定义在 :mod:`campfire.agent.limits`。
"""

from .errors import ModelConfigurationError, ModelError, ModelFailureReason, classify_model_failure
from .gateway import (
    ModelBinding,
    ModelGateway,
    ModelPurpose,
    build_model_settings,
    build_retry_settings,
    resolve_model_name,
    worst_case_model_seconds,
)
from .probe import ModelEndpointReport, check_model_endpoint

__all__ = [
    "ModelBinding",
    "ModelConfigurationError",
    "ModelEndpointReport",
    "ModelError",
    "ModelFailureReason",
    "ModelGateway",
    "ModelPurpose",
    "build_model_settings",
    "build_retry_settings",
    "check_model_endpoint",
    "classify_model_failure",
    "resolve_model_name",
    "worst_case_model_seconds",
]
