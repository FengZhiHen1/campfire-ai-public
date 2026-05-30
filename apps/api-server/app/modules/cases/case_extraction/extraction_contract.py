"""LLM 案例提取服务 — 行为契约（ABC 模板方法）。

定义从 L1 叙事文本中提取 L2 结构化卡片的契约骨架：
- @final extract() = 唯一外部入口，执行 提取 → 校验 → 写入 流水线
- @abstractmethod 钩子 = 实现者填写 LLM 调用和卡片校验逻辑

数据来源:
  - LLMClient (py_llm): MUST — DeepSeek LLM API 调用
  - CaseCard (py_db): MUST — L2 卡片 ORM 模型
  - AsyncSession (sqlalchemy): MUST — 数据库异步会话
边界:
  - 依赖: py_llm, py_db
  - 被依赖: narrative_routes.py 的 extract 端点
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, final

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases.exceptions import ExtractionError
from app.modules.cases.types import NarrativeId


class ExtractionServiceContract(ABC):
    """LLM 提取服务契约。实现者只能覆写 _do_ 前缀的钩子方法。

    异常策略: 契约基类校验器抛出域异常（exceptions.py 中定义）。
    Service 实现可按需包装为 HTTPException。契约层（框架无关）
    与服务层（FastAPI 适配）的异常体系是有意分离的。
    """

    @final
    async def extract_cards_from_narrative(
        self,
        narrative_text: str,
        narrative_id: NarrativeId,
        db: AsyncSession,
    ) -> list[Any]:
        """从 L1 叙事文本提取 L2 结构化卡片。

        流水线: 输入校验 → LLM 调用 → JSON 解析 → 逐卡片校验 → 数据库写入。

        前置:
          - narrative_text 非空
          - narrative_id 为有效 UUID 字符串
        后置:
          - 返回已写入数据库的 CaseCard 列表（review_status=draft）
          - 每张卡片通过字段合法性校验
        异常:
          - ExtractionError: LLM 调用失败、JSON 解析失败或卡片校验不通过
        Side Effects:
          - 写入 case_cards 表（N 条记录）
          - 记录结构化日志（extraction_completed）
        """
        self._validate_extraction_input(narrative_text, narrative_id)
        cards = await self._do_extract(narrative_text, narrative_id, db)
        self._validate_extraction_result(cards, narrative_id)
        return cards

    # ---------------------------------------------------------------------------
    # @abstractmethod 钩子（实现者必填）
    # ---------------------------------------------------------------------------

    @abstractmethod
    async def _do_extract(
        self,
        narrative_text: str,
        narrative_id: NarrativeId,
        db: AsyncSession,
    ) -> list[Any]:
        """执行 LLM 提取的核心逻辑。

        不需要关心: 输入校验（上游 _validate_extraction_input 已处理）。
        实现者在此: LLM 调用 → JSON 解析 → 逐卡片校验 → 数据库写入。
        """
        ...

    # ---------------------------------------------------------------------------
    # 校验器（模板提供基线校验）
    # ---------------------------------------------------------------------------

    def _validate_extraction_input(
        self, narrative_text: str, narrative_id: str
    ) -> None:
        """基线输入校验。"""
        if not narrative_text or not narrative_text.strip():
            raise ValueError("narrative_text 不能为空")
        if not narrative_id:
            raise ValueError("narrative_id 不能为空")

    def _validate_extraction_result(
        self, cards: list[Any], narrative_id: str
    ) -> None:
        """基线后置校验。"""
        if cards is None:
            raise RuntimeError(
                f"ExtractionServiceContract.extract({narrative_id}) 返回了 None"
            )
        if len(cards) == 0:
            raise ExtractionError("LLM 未识别到任何干预场景")
