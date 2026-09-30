"""模型端点探针：健康检查用，不声称模型在业务上可用。

从 `agent/model/__init__.py` 拆出来，是因为它与网关是两件事：网关负责真实调用，
探针只负责如实报告「配没配、通不通」，并且刻意不消耗生成额度、不发送任何使用者数据。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from campfire.core.config import Settings

from .gateway import resolve_model_name

_PROBE_TIMEOUT_SECONDS = 5.0
"""探针单次请求的时间上界。

取值理由：健康检查是聚合等待（多个依赖串起来），因此单个探针不能吃掉调用方的容忍度——
5 秒比一次真实运行的 180 秒上限低一个半数量级，同时足够覆盖一次 `GET /models` 的正常
往返。探针只回答「配没配、通不通」，不值得为它延长整体的健康检查时延。"""


@dataclass(frozen=True, slots=True)
class ModelEndpointReport:
    """模型端点探测结果。

    刻意不返回 `core/health` 的形状：`agent/*` 的依赖白名单只放行
    `core/config`（docs/项目结构设计.md 第 7 节），把结果映射成健康项由装配处
    （`campfire.main`）完成。
    """

    configured: bool
    reachable: bool
    detail: str


def _authorization_header(api_key: SecretStr) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key.get_secret_value()}"}


def _lists_models(payload: object, model_name: str) -> tuple[bool, bool]:
    """响应体是不是一份模型清单，以及清单里有没有配置的模型。

    判形状而不是判名字：TokenHub 返回的 `id` 写法（大小写、是否带版本后缀）尚未核实
    （`TECH-02`），拿名字做硬判定会把「能列出模型但 id 写法不同」误报成不可用。
    因此：形状不对 → 不是模型清单（200 也不可信）；形状对但名字没出现 → 仍报可达，
    但把这件事写进 detail 让运营者自己看。
    """
    if not isinstance(payload, dict):
        return False, False
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return False, False
    ids = {entry.get("id") for entry in data if isinstance(entry, dict)}
    if not ids:
        return False, False
    return True, model_name in ids


async def check_model_endpoint(settings: Settings) -> ModelEndpointReport:
    """探测模型端点。

    本探针不声称模型在业务上可用：`TECH-02`（本账号在 TokenHub 上
    DeepSeek-V4.1-Flash 的实际可用性、RPM/TPM/并发与额度）尚未核实，因此这里
    只报告「已配置 + 端点可达」，不报告额度、并发与响应质量。

    用 `GET /models` 探测：不消耗生成额度，也不发送任何使用者数据。

    200 不等于可达：代理与网关会用 200 返回 HTML 错误页、空 body，甚至带错误码的 JSON。
    因此 200 还要求响应体是一份模型清单（`data` 是非空对象数组）才报可达——实测第一版
    把这些全部报成「端点可达」，与「证据强度与措辞匹配」不符。
    """
    model_name = resolve_model_name(settings)
    if settings.tokenhub_api_key is None:
        return ModelEndpointReport(False, False, "未配置 TOKENHUB_API_KEY")

    url = f"{settings.tokenhub_base_url.rstrip('/')}/models"
    headers = _authorization_header(settings.tokenhub_api_key)
    try:
        # 与内网探针不同，这里保留 trust_env：TokenHub 是外部服务，
        # 企业网络下可能需要经代理访问。代价是宿主机代理配置异常时探针也会失败，
        # 故下面把 InvalidURL 单独区分出来。
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=headers)
    except (httpx.InvalidURL, httpx.UnsupportedProtocol):
        # 配置问题，不是可达性问题。实测两类都要覆盖：坏端口抛 InvalidURL，
        # 缺协议头/错协议抛 UnsupportedProtocol。已知实例：no_proxy 含 [::1]。
        return ModelEndpointReport(
            True,
            False,
            "TOKENHUB_BASE_URL 或宿主机代理配置不是合法 URL",
        )
    except (httpx.HTTPError, OSError, TimeoutError) as exc:
        # 只把传输类异常说成不可达：其余异常（探针自身的编程错误）不得被描述成网络问题，
        # 否则会把排查者引向错误方向。
        return ModelEndpointReport(True, False, f"{model_name} 端点不可达（{type(exc).__name__}）")
    except Exception as exc:  # noqa: BLE001 —— 但仍如实说明「这不是可达性结论」
        return ModelEndpointReport(
            True,
            False,
            f"探针自身异常（{type(exc).__name__}），无法判定端点状态",
        )

    if response.status_code != 200:
        return ModelEndpointReport(True, False, f"{model_name} 端点返回 {response.status_code}")

    try:
        payload = response.json()
    except ValueError:
        return ModelEndpointReport(
            True, False, f"{model_name} 端点返回 200，但响应体不是 JSON（可能是错误页或代理响应）"
        )

    listed, named = _lists_models(payload, model_name)
    if not listed:
        return ModelEndpointReport(
            True,
            False,
            f"{model_name} 端点返回 200，但响应体不是模型清单（可能是错误页或代理响应）",
        )
    if not named:
        return ModelEndpointReport(
            True,
            True,
            f"{model_name} 端点可达，但该模型未出现在 /models 清单里（id 写法未核实，见 TECH-02）",
        )
    return ModelEndpointReport(
        True,
        True,
        f"{model_name} 端点可达（额度与并发未核实，见 TECH-02）",
    )
