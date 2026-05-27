"""PROF-05 档案隐私控制 — Pydantic Schema 定义。

提供全平台共享的档案操作类型枚举、可见范围枚举、
访问请求输入模型和访问裁决输出模型。

对外接口类型定义与 docs/contracts/PROF-05/ 下的 JSON Schema 契约一致。
PROF-05 作为定义方，下游模块 PROF-01/PROF-03/PROF-04 作为消费方。

契约引用：
- AccessOperation: docs/contracts/PROF-05/AccessOperation.json
- VisibleScope: docs/contracts/PROF-05/VisibleScope.json
- AccessRequest: docs/contracts/PROF-05/AccessRequest.json
- AccessDecision: docs/contracts/PROF-05/AccessDecision.json
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class AccessOperation(StrEnum):
    """个人档案操作类型枚举。

    定义可对个人档案执行的全部操作种类，六值枚举：
    - VIEW: 查看档案内容
    - CREATE: 新增档案数据
    - UPDATE: 修改档案数据
    - DELETE: 删除档案数据
    - SUPPLEMENT_ASSESSMENT: 补充专业评估
    - UNLINK: 解除老师关联

    与 docs/contracts/PROF-05/AccessOperation.json 契约一致。
    """

    VIEW = "view"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SUPPLEMENT_ASSESSMENT = "supplement_assessment"
    UNLINK = "unlink"


class VisibleScope(StrEnum):
    """档案数据可见范围枚举。

    定义访问被允许时请求人可查看的数据范围，三值枚举：
    - ALL_FIELDS: 全部字段可见（家属、关联老师/专家）
    - METADATA_ONLY: 仅元数据可见（管理员）
    - NOTHING: 无可见内容（非关联用户/拒绝时）

    与 docs/contracts/PROF-05/VisibleScope.json 契约一致。
    """

    ALL_FIELDS = "all_fields"
    METADATA_ONLY = "metadata_only"
    NOTHING = "none"


class AccessRequest(BaseModel):
    """档案访问请求输入模型。

    封装一次档案访问请求的全部上下文信息，由下游模块（PROF-01/03/04）
    在执行档案操作前构造并传递给 PrivacyGuard.check_access() 进行权限校验。

    与 docs/contracts/PROF-05/AccessRequest.json 契约一致。

    Attributes:
        operation: 请求执行的操作类型，必须在 AccessOperation 枚举值范围内。
        target_profile_id: 目标个人档案的唯一标识。
        requester_id: 请求发起人的用户唯一标识。
        requester_role: 请求发起人的角色枚举值（family/teacher/expert/admin/maintainer）。
        relation_type: 请求人与目标档案的关联关系类型（可选）。
    """

    operation: AccessOperation = Field(
        ...,
        description="请求执行的操作类型，必须在 AccessOperation 枚举值范围内",
    )
    target_profile_id: UUID = Field(
        ...,
        description="目标个人档案的唯一标识，必须对应 profiles 表中的有效记录",
    )
    requester_id: UUID = Field(
        ...,
        description="请求发起人的用户唯一标识，必须是已通过 AUTH-04 鉴权的有效用户",
    )
    requester_role: str = Field(
        ...,
        pattern="^(family|teacher|expert|admin|maintainer)$",
        description="请求发起人的角色枚举值，必须是五级角色之一",
    )
    relation_type: str | None = Field(
        default=None,
        description=(
            "请求人与目标档案的关联关系类型。"
            "linked_teacher/linked_expert 表示已关联，"
            "family_member 表示同家庭家属，none 表示无关联"
        ),
    )

    model_config = {"extra": "forbid"}


class AccessDecision(BaseModel):
    """档案访问裁决输出模型。

    封装 PrivacyGuard.check_access() 对一次档案访问请求的裁决结论。
    被下游模块（PROF-01/03/04）消费以决定是否继续执行数据库操作。

    与 docs/contracts/PROF-05/AccessDecision.json 契约一致。

    Attributes:
        allowed: 访问许可结果。true 表示允许，false 表示拒绝。
        visible_scope: 可见数据范围。allowed=true 时值取决于角色；allowed=false 时固定为 nothing。
        denial_reason: 拒绝原因。allowed=false 时必填，值为泛化消息"数据不存在"。
    """

    allowed: bool = Field(
        ...,
        description="访问许可结果。true 表示允许执行所请求的操作，false 表示拒绝",
    )
    visible_scope: VisibleScope = Field(
        ...,
        description=(
            "可见数据范围。allowed=true 时值取决于角色和访问矩阵"
            "（all_fields/metadata_only）；allowed=false 时固定为 none"
        ),
    )
    denial_reason: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "拒绝原因。allowed=false 时必填，值必须为泛化消息'数据不存在'。"
            "allowed=true 时为 null"
        ),
    )

    model_config = {"extra": "forbid"}


__all__ = [
    "AccessOperation",
    "VisibleScope",
    "AccessRequest",
    "AccessDecision",
]
