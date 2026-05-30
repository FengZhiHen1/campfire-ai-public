# @contract
"""py-schemas 共享基类。

提供 CampfireBaseModel —— 全平台 Pydantic 模型的统一基类，
强制 extra='forbid' 以防止未声明字段的静默传入。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CampfireBaseModel(BaseModel):
    """全平台共享 Pydantic 基类。

    统一配置：
    - extra='forbid': 禁止未声明的额外字段，防止 Silent Data Corruption
    - 所有 py_schemas 下的模型均继承此类，而非直接继承 pydantic.BaseModel
    """

    model_config = ConfigDict(extra="forbid")
