"""模型网关与路由：**模型名在代码中的唯一出现处**。

归属（见 docs/项目结构设计.md 第 10 节）：模型名唯一出现处；业务代码不得硬编码
模型名。取值来自 ``core/config``，依赖方向 ``agent → core/config`` 在第 7 节
白名单内。基座不含领域术语，本模块同样不含。

供应商约束（见 docs/技术栈设计.md 第 3 节）：腾讯云 TokenHub 是外部数据处理方。
`EVID-C` 未关闭前只发送虚构或经核准不可识别的样例（``RQ-LIM-03``）。
"""

from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from campfire.core.config import Settings


@dataclass(frozen=True, slots=True)
class ModelEndpointReport:
    """模型端点探测结果。

    刻意**不返回** ``core/health`` 的形状：``agent/*`` 的依赖白名单只放行
    ``core/config``（docs/项目结构设计.md 第 7 节），把结果映射成健康项由装配处
    （``campfire.main``）完成。
    """

    configured: bool
    reachable: bool
    detail: str


def resolve_model_name(settings: Settings) -> str:
    """返回本次运行使用的模型名。业务代码只经此函数取模型名。"""
    return settings.model_name


def _authorization_header(api_key: SecretStr) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key.get_secret_value()}"}


async def check_model_endpoint(settings: Settings) -> ModelEndpointReport:
    """探测模型端点。

    **本探针不声称模型在业务上可用**：``TECH-02``（本账号在 TokenHub 上
    DeepSeek-V4.1-Flash 的实际可用性、RPM/TPM/并发与额度）尚未核实，因此这里
    只报告「已配置 + 端点可达」，不报告额度、并发与响应质量。

    用 ``GET /models`` 探测：不消耗生成额度，也不发送任何使用者资料。
    """
    model_name = resolve_model_name(settings)
    if settings.tokenhub_api_key is None:
        return ModelEndpointReport(False, False, "未配置 TOKENHUB_API_KEY")

    url = f"{settings.tokenhub_base_url.rstrip('/')}/models"
    headers = _authorization_header(settings.tokenhub_api_key)
    try:
        # 与内网探针不同，这里**保留** trust_env：TokenHub 是外部服务，
        # 企业网络下可能需要经代理访问。代价是宿主机代理配置异常时探针也会失败，
        # 故下面把 InvalidURL 单独区分出来。
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers)
    except (httpx.InvalidURL, httpx.UnsupportedProtocol):
        # 配置问题，不是可达性问题。实测两类都要覆盖：坏端口抛 InvalidURL，
        # 缺协议头/错协议抛 UnsupportedProtocol。
        return ModelEndpointReport(
            True,
            False,
            "TOKENHUB_BASE_URL 或宿主机代理配置不是合法 URL",
        )
    except Exception as exc:  # noqa: BLE001 —— 探针吞掉一切网络异常并如实上报
        return ModelEndpointReport(True, False, f"{model_name} 端点不可达（{type(exc).__name__}）")

    if response.status_code == 200:
        return ModelEndpointReport(
            True,
            True,
            f"{model_name} 端点可达（额度与并发未核实，见 TECH-02）",
        )
    return ModelEndpointReport(True, False, f"{model_name} 端点返回 {response.status_code}")
