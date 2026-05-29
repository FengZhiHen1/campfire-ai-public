"""py-llm: Campfire-AI 的 LLM API 客户端包。

通过 DeepSeek API（OpenAI 兼容协议）提供统一的 LLM 客户端接口，
支持流式和非流式聊天补全。

分层架构:
- types.py — 数据形状契约（Pydantic 模型 + RetryConfig）
- llm_contract.py — 行为契约（ABC 模板方法：@final 入口 + @abstractmethod 钩子）
- client.py — 具体实现（继承 LLMClientContract）
"""

from py_llm.client import LLMClient
from py_llm.llm_contract import LLMClientContract, LLMClientError
from py_llm.types import ChatCompletionChunk, Choice, Delta, RetryConfig

__all__ = [
    "LLMClient",
    "LLMClientContract",
    "LLMClientError",
    "ChatCompletionChunk",
    "Choice",
    "Delta",
    "RetryConfig",
]
