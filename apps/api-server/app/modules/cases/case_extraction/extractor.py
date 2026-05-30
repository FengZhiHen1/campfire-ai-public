"""LLM 案例提取服务。

从 L1 自然语言叙事中，调用 DeepSeek（JSON Mode）提取 N 张 L2 结构化卡片。
Prompt 设计参照 case-extraction skill，以 ebp_reference.md 为约束字典。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from py_llm import LLMClient
from py_db.models.case_card import CaseCard

from app.modules.cases.case_extraction.extraction_contract import ExtractionServiceContract
from app.modules.cases.exceptions import ExtractionError
from app.modules.cases.types import NarrativeId

_logger = logging.getLogger(__name__)

# NCAEP 28 种 EBP 标签（用于反向校验）
_VALID_EBP_TAGS: frozenset[str] = frozenset({
    "前因干预(ABI)", "辅助替代沟通(AAC)", "行为动力干预(BMI)",
    "认知行为策略(CBI)", "差别强化(DR)", "直接教学(DI)",
    "离散试教学(DTT)", "消退(EXT)", "功能行为评估(FBA)",
    "功能沟通训练(FCT)", "自然主义干预(NI)", "家属实施干预(PII)",
    "同伴教学(PBI)", "提示(PP)", "强化(R)",
    "反应中断/重定向(RIR)", "自我管理(SM)", "社交叙事(SN)",
    "社交技能训练(SST)", "任务分析(TA)", "视频示范(VM)",
    "视觉支持(VS)", "运动与锻炼(Exercise)", "功能沟通(Functional Communication)",
    "示范(Modeling)", "音乐辅助干预(Music-Mediated Intervention)",
    "感觉统合(Sensory Integration)", "技术辅助干预(Technology-Aided Intervention)",
})

_VALID_PARENT_CATEGORIES: frozenset[str] = frozenset({
    "环境调整", "沟通替代", "行为塑造", "危机安全", "社交引导", "自我管理",
})

_VALID_BEHAVIOR_TYPES: frozenset[str] = frozenset({
    "自伤", "攻击", "刻板", "逃跑", "情绪崩溃", "其他",
})

_VALID_SEVERITY: frozenset[str] = frozenset({"轻", "中", "重"})
_VALID_SETTINGS: frozenset[str] = frozenset({"家庭", "学校", "公共场合", "机构", "不限"})

# ============================================================================
# System Prompt（基于 case-extraction skill 步骤 1-4）
# ============================================================================

_EXTRACTION_SYSTEM_PROMPT = """你是一名孤独症行为干预案例提取专家。你的任务是从家属/专家的自然语言叙事中，提取结构化的干预协议卡片。

## 约束字典

### 行为类型枚举（behavior_type 必须从中选一项）
- 自伤：自我伤害行为（撞头、咬手、抓挠等）
- 攻击：指向他人的攻击行为（打人、踢人、咬人等）
- 刻板：刻板/重复行为（摇晃、转圈、重复语言等）
- 逃跑：逃跑/离开安全环境行为
- 情绪崩溃：情绪爆发/崩溃（哭闹、尖叫、倒地等）
- 其他：以上分类无法覆盖的行为

### 严重程度枚举（severity_level）
- 轻：行为可被简单安抚或环境调整终止，无安全风险
- 中：行为持续数分钟，需要结构化干预，有轻微安全风险
- 重：行为持续10分钟以上，存在自伤/伤人或严重环境破坏风险

### 场景枚举（setting）
家庭 / 学校 / 公共场合 / 机构 / 不限

### EBP 标签（ebp_tags，从以下 28 种中选择 2-4 个最匹配的）
前因干预(ABI) / 辅助替代沟通(AAC) / 行为动力干预(BMI) / 认知行为策略(CBI) / 差别强化(DR) / 直接教学(DI) / 离散试教学(DTT) / 消退(EXT) / 功能行为评估(FBA) / 功能沟通训练(FCT) / 自然主义干预(NI) / 家属实施干预(PII) / 同伴教学(PBI) / 提示(PP) / 强化(R) / 反应中断/重定向(RIR) / 自我管理(SM) / 社交叙事(SN) / 社交技能训练(SST) / 任务分析(TA) / 视频示范(VM) / 视觉支持(VS) / 运动与锻炼 / 功能沟通 / 示范 / 音乐辅助干预 / 感觉统合 / 技术辅助干预

### 家属端大类映射（parent_category，从 6 类中选 1 个）
- 环境调整：前因干预、视觉支持、感觉统合相关策略 — 减少触发因素、调整物理环境
- 沟通替代：AAC、功能沟通训练、社交叙事 — 替代问题行为的功能性表达
- 行为塑造：DTT、直接教学、任务分析、提示、强化、差别强化 — 分步骤教授新技能
- 危机安全：反应中断/重定向、消退、FBA — 阻断危险行为、紧急降级
- 社交引导：同伴教学、社交技能训练、自然主义干预 — 同伴互动、社交场景适应
- 自我管理：自我管理、认知行为策略、视频示范 — 情绪调节、自我监控

### 循证等级
固定为 "INSTITUTIONAL"（机构经验总结），由专家审核时决定是否升级。

## 提取流程

### 步骤 1：识别独立干预场景
通读叙事全文，识别其中描述的独立干预事件。每个场景应是围绕一个特定行为问题的完整干预过程。

### 步骤 2：通用化改写
将个体描述转化为通用场景。去掉真实姓名、具体地名、日期，保留年龄区间、行为类型、干预策略。

### 步骤 3：四段式提取
对每个场景提取四个核心字段：
- immediate_action：即时干预动作（具体可执行的动作序列，按步骤编号）
- comforting_phrase：安抚话术（可直接使用的安抚语言，用引号标注话术示例）
- observation_metrics：观察指标（可量化、可观测的具体指标，含数值阈值）
- medical_criteria：就医判断标准（明确的底线条件，含具体阈值）

四项必须全部非空。

### 步骤 4：循证标注 + 反向校验
- 根据干预动作的本质机制匹配 EBP 标签（2-4个）
- 反向校验：自问每个标签的定义边界是否真的匹配，剔除"沾边"的标签
- 根据 ebp_tags 占比确定 parent_category
- 至少列出 2 个候选 parent_category 及权衡理由，记录到 _inferred 中

## 推断规则
- 叙事中直接提到的值，不标记为推断
- 从间接信息推导的值（如从"上小学"推断年龄6-12岁），标记到 _inferred
- 完全无法推断的必填字段，填入最保守值并标记推断

## 输出格式
你必须返回一个严格的 JSON 对象，格式如下：
```json
{
  "cards": [
    {
      "title": "干预策略简述 - 适用场景",
      "scenario": "适用场景的完整描述（2-4句）",
      "behavior_type": "情绪崩溃",
      "age_range": ["6", "12"],
      "severity_level": "中",
      "setting": "公共场合",
      "ebp_tags": ["前因干预(ABI)", "视觉支持(VS)"],
      "parent_category": "环境调整",
      "immediate_action": "1. ...\\n2. ...",
      "comforting_phrase": "\\"我们先去那边安静的地方坐一下\\"",
      "observation_metrics": "1. 3分钟内哭声停止\\n2. ...",
      "medical_criteria": "1. 行为持续超过30分钟\\n2. ...",
      "evidence_level": "INSTITUTIONAL",
      "caution_notes": "不要在患者情绪高峰时强行身体约束",
      "contraindications": "无",
      "is_template": false,
      "_inferred": {
        "age_range": "叙事提到'小学二年级'，推断为7-8岁学龄期",
        "parent_category_candidates": "候选1: 环境调整（前因策略为主，移除触发源）; 候选2: 危机安全（干预含紧急降级动作）"
      }
    }
  ]
}
```

age_range 始终用字符串数组。caution_notes 若无可填空字符串。contraindications 若无可填 "无"。
"""


# ============================================================================
# 提取服务实现
# ============================================================================


class ExtractionService(ExtractionServiceContract):
    """LLM 提取服务实现。实现 ExtractionServiceContract 契约的 _do_extract 钩子。"""

    async def _do_extract(
        self,
        narrative_text: str,
        narrative_id: NarrativeId,
        db: AsyncSession,
    ) -> list[Any]:
        """执行 LLM 提取的核心逻辑。

        LLM 调用 → JSON 解析 → 逐卡片校验 → 数据库写入。
        """
        client = LLMClient()

        messages = [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"请从以下叙事中提取干预卡片：\n\n{narrative_text}\n\nYour response must be a valid JSON object."},
        ]

        # 调用 LLM（JSON Mode）
        try:
            response_text = await client.async_chat(
                messages=messages,
                model="deepseek-v4-pro",
                temperature=0.3,
                max_tokens=8192,
                timeout=30.0,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            _logger.exception("llm_extraction_failed")
            raise ExtractionError(str(exc)) from exc

        # 解析 JSON
        try:
            # 清理可能的 markdown 代码块包裹
            cleaned = re.sub(
                r"^```(?:json)?\s*|\s*```$", "",
                response_text.strip(), flags=re.MULTILINE,
            )
            result = json.loads(cleaned)
            cards_data = result.get("cards", [])
        except (json.JSONDecodeError, KeyError) as exc:
            _logger.error(
                "extraction_parse_failed", extra={"raw": response_text[:500]},
            )
            raise ExtractionError(f"JSON 解析失败: {exc}") from exc

        # 逐卡片校验 + 写入数据库
        cards: list[Any] = []
        nid = uuid.UUID(narrative_id)

        for i, raw in enumerate(cards_data):
            errors = self._validate_card(raw, i)
            if errors:
                raise ExtractionError(
                    f"卡片 {i+1} 校验失败: {'; '.join(errors)}",
                )

            card = CaseCard(
                card_id=uuid.uuid4(),
                narrative_id=nid,
                title=raw["title"],
                scenario=raw["scenario"],
                behavior_type=raw["behavior_type"],
                age_range_min=int(raw["age_range"][0]),
                age_range_max=int(raw["age_range"][1]),
                severity=raw["severity_level"],
                scene=raw["setting"],
                ebp_labels=raw.get("ebp_tags", []),
                family_category=raw["parent_category"],
                immediate_action=raw["immediate_action"],
                comforting_phrase=raw["comforting_phrase"],
                observation_metrics=raw["observation_metrics"],
                medical_criteria=raw["medical_criteria"],
                evidence_level=raw.get("evidence_level", "INSTITUTIONAL"),
                caution_notes=raw.get("caution_notes", ""),
                contraindications=raw.get("contraindications", "无"),
                is_template=raw.get("is_template", False),
                review_status="draft",
                _inferred=raw.get("_inferred") or raw.get("inferred_fields"),
            )
            db.add(card)
            cards.append(card)

        await db.commit()
        for c in cards:
            await db.refresh(c)

        _logger.info("extraction_completed", extra={
            "narrative_id": narrative_id, "card_count": len(cards),
        })
        return cards

    # ========================================================================
    # 卡片字段校验
    # ========================================================================

    @staticmethod
    def _validate_card(raw: dict, index: int) -> list[str]:
        """校验单张卡片的字段完整性和合法性。"""
        errors: list[str] = []

        required = [
            "title", "scenario", "behavior_type", "severity_level", "setting",
            "immediate_action", "comforting_phrase", "observation_metrics",
            "medical_criteria", "parent_category",
        ]
        for field in required:
            if not raw.get(field):
                errors.append(f"缺少必填字段 {field}")

        if raw.get("behavior_type") not in _VALID_BEHAVIOR_TYPES:
            errors.append(f"无效 behavior_type: {raw.get('behavior_type')}")
        if raw.get("severity_level") not in _VALID_SEVERITY:
            errors.append(f"无效 severity_level: {raw.get('severity_level')}")
        if raw.get("setting") not in _VALID_SETTINGS:
            errors.append(f"无效 setting: {raw.get('setting')}")
        if raw.get("parent_category") not in _VALID_PARENT_CATEGORIES:
            errors.append(f"无效 parent_category: {raw.get('parent_category')}")

        age_range = raw.get("age_range", [])
        if not isinstance(age_range, list) or len(age_range) != 2:
            errors.append("age_range 必须是 [min, max] 格式的数组")

        ebp_tags = raw.get("ebp_tags", [])
        if not isinstance(ebp_tags, list) or len(ebp_tags) == 0:
            errors.append("ebp_tags 必须是非空数组")
        else:
            for tag in ebp_tags:
                if tag not in _VALID_EBP_TAGS:
                    errors.append(f"无效 EBP 标签: {tag}")

        return errors

__all__ = [
    "ExtractionService",
]
