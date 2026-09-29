"""嵌入适配：TokenHub 的 OpenAI 兼容嵌入端点。

归属（见 docs/技术设计/technical-details/RAG策略.md 第 2 节与
docs/技术设计/decisions/检索链归入library模块.md）：嵌入适配是检索链的一部分，
因此归本模块。模型名取自 ``core/config``——**它是嵌入模型名的唯一配置处**
（``core/*`` 不得依赖 ``agent/*``，故不能放 ``agent/model``）。凭据复用
``tokenhub_base_url``/``tokenhub_api_key``，不引入第二套凭据。

**实测得到的三个约束**（2026-09-29）：

- 框架的 ``OpenAIEmbedding`` 用 **``model_name=`` 而非 ``model=``** 构造：``model``
  会被当作 ``OpenAIEmbeddingModelType`` 枚举校验，我们的 ``Kinfra-Text-Embedding-4b``
  不在枚举内，会抛 ``ValueError: ... is not a valid OpenAIEmbeddingModelType``；
  传 ``model_name`` 则直接采用自定义名（见框架 ``base.py`` 的 ``if "model_name" in kwargs``
  分支）。这是设计「经 OpenAI 兼容嵌入适配接入」的可行入口。
- **单条文本硬上限 2000 字符**、单请求建议 ≤128 条——分块后处理与批量大小都据此设定
  （RAG 策略第 1.2 节与第 10 节）。
- 凭据为空时**显式失败**，不静默降级：缺凭据的嵌入会产出一批零向量或报错，
  两者都比「明确说没配」更危险。

维度（2560）**不做成可配置项**：它与模型绑定，作为常量定义在本模块，
可配置的维度会诱发配错维度混库（RAG 策略第 7 节纪律 4）。
"""

from __future__ import annotations

import httpx
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding

from campfire.core.config import EMBEDDING_DIM, Settings

#: 嵌入维度：**定义在 ``core/config``**（与嵌入模型名的唯一配置处同位），此处只转出。
#: 之所以不在本模块定义：记忆侧（`modules/memory` 的 Graphiti 嵌入器）必须用同一个
#: 维度（RAG 策略第 11 节），而 `modules/*` 之间不得互相 import（项目结构设计第 7 节）
#: ——两处各写一份数字就是第二真源。详见 core/config 的常量注释。
__all__ = [
    "EMBEDDING_DIM",
    "EMBEDDING_MAX_RETRIES",
    "EMBEDDING_TIMEOUT_SECONDS",
    "MAX_TEXT_CHARS",
    "RECOMMENDED_BATCH_SIZE",
    "EmbeddingConfigurationError",
    "assert_text_within_limit",
    "build_embedding",
]

#: 单条文本硬上限（字符）。TokenHub 嵌入接口限制；分块后处理据此设定硬限。
MAX_TEXT_CHARS = 2000

#: 单请求建议批量上限。这是**建议值**：超过它不会被拒，但会拉长单次请求耗时，
#: 对应急路径的时延预算不利。
RECOMMENDED_BATCH_SIZE = 128

#: 单次嵌入请求超时（秒）。**有界**：检索链在应急路径上（首字 ≤10 秒），
#: 嵌入是其中一环，不能无限等待；超时按失败处理并走降级语义。
EMBEDDING_TIMEOUT_SECONDS = 30.0

#: 重试次数。定得比对话模型低：嵌入失败可降级到字面路（失败语义第 5 节），
#: 不值得为它吃掉应急时延预算。
EMBEDDING_MAX_RETRIES = 2


class EmbeddingConfigurationError(Exception):
    """嵌入配置不可用：缺凭据。

    这是**启动期/首次调用就该暴露**的错误，不可能靠重试解决——与
    ``ModelConfigurationError`` 同属一类，但归 ``core``/``modules`` 侧，
    因此单独定义而不 import ``agent/*``（白名单禁止）。
    """


def build_embedding(settings: Settings) -> BaseEmbedding:
    """按配置构造嵌入器。

    返回框架的 ``BaseEmbedding``，因此调用方既能用 ``get_text_embedding``
    系列方法，也能把它交给 ``VectorStoreIndex`` 一类框架组件。

    Raises:
        EmbeddingConfigurationError: 未配置 ``TOKENHUB_API_KEY`` 时——显式失败，
            不静默降级（见模块说明）。
    """
    if settings.tokenhub_api_key is None:
        raise EmbeddingConfigurationError("未配置 TOKENHUB_API_KEY，无法调用嵌入服务")

    # trust_env=False：宿主机 no_proxy 含带方括号的 IPv6 字面量时，默认客户端
    # 构造会抛 InvalidURL（本机实测，conftest 已留档）。嵌入是服务端到服务端调用，
    # 不需要继承桌面环境的代理豁免列表；企业网络需要代理时应显式配置。
    http_client = httpx.AsyncClient(trust_env=False, timeout=EMBEDDING_TIMEOUT_SECONDS)

    return OpenAIEmbedding(
        # 必须用 model_name=（见模块说明：model= 会走枚举校验）。
        model_name=settings.embedding_model_name,
        api_key=settings.tokenhub_api_key.get_secret_value(),
        api_base=settings.tokenhub_base_url,
        embed_batch_size=RECOMMENDED_BATCH_SIZE,
        timeout=EMBEDDING_TIMEOUT_SECONDS,
        max_retries=EMBEDDING_MAX_RETRIES,
        async_http_client=http_client,
    )


def assert_text_within_limit(text: str) -> None:
    """校验单条文本未超嵌入接口硬限。

    在**送入嵌入之前**调用：超限的文本会被供应商拒绝或（更糟）被静默截断，
    而截断会制造错误的检索依据。分块后处理已保证不超限；此函数是最后一道
    闸门，防止绕过流水线的调用（例如测试或将来新增的入口）。

    Raises:
        ValueError: 文本超过 ``MAX_TEXT_CHARS`` 时，附上实际长度便于定位。
    """
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"单条文本 {len(text)} 字符，超过嵌入接口硬上限 {MAX_TEXT_CHARS}")
