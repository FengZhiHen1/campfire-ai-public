# @contract
"""MVP Phase 1: 应急咨询触发端点 Schema。

提供 POST /api/v1/consult 的输入/输出模型。
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from py_schemas.base import CampfireBaseModel


class ConsultStartRequest(CampfireBaseModel):
    """提交应急咨询的请求体。"""

    behavior_description: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="家属描述的患者当前行为与情绪表现",
    )
    profile_id: UUID | None = Field(
        default=None,
        description="关联的患者档案 ID（可选）。若提供，将提取档案标签注入检索",
    )
    behavior_type: list[
            Literal[
                "SELF_INJURY", "AGGRESSION", "ELOPEMENT", "MEDICATION",
                "EMOTIONAL_MELTDOWN", "STEREOTYPY", "OTHER",
            ]
        ] | None = Field(
        default=None,
        min_length=1,
        description="前置行为类型选择（可选，可多选）",
    )
    emotion_level: Literal["轻", "中", "重"] | None = Field(
        default=None,
        description="情绪等级（可选）",
    )



class ConsultStartResponse(CampfireBaseModel):
    """提交应急咨询的响应体。"""

    session_id: str = Field(
        ...,
        description="SSE 流式推送会话 ID。客户端随后连接 GET /api/v1/consult/stream/{session_id}",
    )



__all__ = ["ConsultStartRequest", "ConsultStartResponse"]
