"""py-llm 语法契约：类型定义、数据模型、配置对象。

本文件是 py-llm 包的数据形状"单一真相源"。
所有公开接口必须使用此处的类型，禁止裸用原始类型。
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


# ============================================================================
# 重试配置
# ============================================================================


@dataclass(frozen=True)
class RetryConfig:
    """指数退避重试配置（不可变）。

    Attributes:
        max_retries: 最大重试次数，默认 3。
        base_delay: 基础延迟秒数，默认 3.0。
        max_delay: 最大延迟秒数上限，默认 120.0。
    """

    max_retries: int = 3
    base_delay: float = 3.0
    max_delay: float = 120.0

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        if self.base_delay <= 0:
            raise ValueError(f"base_delay must be > 0, got {self.base_delay}")
        if self.max_delay < self.base_delay:
            raise ValueError(
                f"max_delay ({self.max_delay}) must be >= base_delay ({self.base_delay})"
            )


# ============================================================================
# 流式响应模型（OpenAI 兼容 SSE chunk 表达）
# ============================================================================


class Delta(BaseModel):
    """流式增量内容 — 对应 OpenAI streaming 格式中的 choice.delta。"""

    content: str = Field(default="", description="本 chunk 的文本增量")
    role: str | None = Field(default=None, description="角色标识，仅首个 chunk 出现")


class Choice(BaseModel):
    """单个流式选项 — 对应 OpenAI streaming 格式中的 choices[0]。"""

    delta: Delta = Field(default_factory=Delta, description="本选项的增量内容")
    index: int = Field(default=0, description="选项索引")
    finish_reason: str | None = Field(default=None, description="结束原因: stop|length|content_filter|null")


class ChatCompletionChunk(BaseModel):
    """流式聊天补全块 — 对应 OpenAI streaming 响应 chunk。"""

    id: str = Field(default="", description="Chunk ID")
    object: str = Field(default="chat.completion.chunk", description="对象类型")
    created: int = Field(default=0, description="Unix 时间戳")
    model: str = Field(default="deepseek-v4-pro", description="模型名称")
    choices: list[Choice] = Field(default_factory=list, description="流式选项列表")
