"""py-agent-kernel 工具契约（pi AgentTool 语义移植）。

工具接口仿 pi 的 AgentTool：
- name/label/description/parameters/execution_mode
- execute 五参签名：tool_call_id / params / signal / on_update / ctx
- ToolResult：content blocks（text/image）+ details
- 错误语义：工具抛异常 → 内核捕获 → isError 回传模型，禁止伪装正常 content
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

# ===========================================================================
# Content blocks（与 pi 同构）
# ===========================================================================


class TextContent(BaseModel):
    """文本内容块。"""

    type: Literal["text"] = "text"
    text: str


class ImageContent(BaseModel):
    """图片内容块（base64 内联或 URL 引用）。"""

    type: Literal["image"] = "image"
    data: str = Field(..., description="base64 编码数据或 URL")
    mime_type: str = Field(default="image/png")


ContentBlock = TextContent | ImageContent


class ToolResult(BaseModel):
    """工具执行结果。

    content 为内容块列表（text/image，与 pi 同构）；
    details 为结构化附加数据（宿主侧消费，如审计元数据）。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    content: list[ContentBlock] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def text(cls, text: str, **details: Any) -> "ToolResult":
        """便捷构造：单文本块结果。"""
        return cls(content=[TextContent(text=text)], details=details)


# ===========================================================================
# CancellationToken / ToolContext
# ===========================================================================


class CancellationToken:
    """取消令牌（asyncio.Event 桥接）。

    宿主可通过 cancel() 请求取消；工具实现应在长任务循环中检查
    is_cancelled 或调用 raise_if_cancelled() 响应取消。
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise asyncio.CancelledError()


class ToolContext:
    """工具执行上下文（pi ExtensionContext 子集）。

    内核暴露会话只读访问与工作目录，供审计、状态类工具使用。
    """

    def __init__(
        self,
        session_id: str,
        cwd: str | None = None,
        session_reader: Any | None = None,
    ) -> None:
        self.session_id = session_id
        self.cwd = cwd
        self._session_reader = session_reader

    @property
    def session_reader(self) -> Any | None:
        """会话只读访问器（内核注入；无会话时 None）。"""
        return self._session_reader


# ===========================================================================
# AgentTool 契约
# ===========================================================================


class AgentTool(ABC, BaseModel):
    """Agent 工具契约（pi AgentTool 移植）。

    实现者职责（安全原则——工具自带校验）：
    - 工具实现内必须自行做权限与参数业务校验，不信任调用上下文；
    - 失败抛异常——内核捕获后以 isError: true 回传模型，
      禁止把错误信息伪装成正常 content 返回（pi 约定）。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(..., description="工具名（蛇形命名，白名单寻址键）")
    label: str = Field(..., description="展示名")
    description: str = Field(..., description="工具说明（注入模型可见的工具描述）")
    parameters: type[BaseModel] = Field(..., description="参数 Pydantic 模型（生成 JSON Schema）")
    execution_mode: Literal["parallel", "sequential"] | None = Field(
        default=None,
        description="执行模式屏障：sequential 经 pydantic-ai per-tool sequential 承载",
    )

    @abstractmethod
    async def execute(
        self,
        tool_call_id: str,
        params: BaseModel,
        signal: CancellationToken,
        on_update: Callable[[ToolResult], None] | None,
        ctx: ToolContext,
    ) -> ToolResult:
        """执行工具。

        Args:
            tool_call_id: 工具调用唯一标识（审计关联）。
            params: 已通过 parameters 模型校验的参数实例。
            signal: 取消令牌。
            on_update: 进度更新回调（中间态 ToolResult，可 None）。
            ctx: 工具执行上下文。

        Returns:
            ToolResult: 内容块 + details。

        Raises:
            Exception: 业务失败——内核捕获后以 isError 回传模型。
        """
        ...


__all__ = [
    "TextContent",
    "ImageContent",
    "ContentBlock",
    "ToolResult",
    "CancellationToken",
    "ToolContext",
    "AgentTool",
]
