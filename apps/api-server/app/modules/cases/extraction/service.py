"""LLM 案例提取服务。

从 L1 自然语言叙事中，调用 DeepSeek（JSON Mode）提取 N 张 L2 结构化卡片。
Prompt 设计参照 case-extraction skill，以 ebp_reference.md 为约束字典。
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from py_logger import logger
from sqlalchemy.ext.asyncio import AsyncSession

from py_llm import LLMClient
from py_db.models.case_card import CaseCard
from py_schemas.cases import NCAEP_EBP_LABELS

from .contract import ExtractionServiceContract
from ..exceptions import ExtractionError
from ..types import NarrativeId

# NCAEP 循证实践标准标签集（与 py_schemas.cases.NCAEP_EBP_LABELS 保持一致，
# 用于 EBP 一致性校验和下游检索）
_VALID_EBP_TAGS: frozenset[str] = frozenset(NCAEP_EBP_LABELS)

_VALID_PARENT_CATEGORIES: frozenset[str] = frozenset({
    "环境调整", "沟通替代", "行为塑造", "危机安全", "社交引导", "自我管理",
})

_VALID_BEHAVIOR_TYPES: frozenset[str] = frozenset({
    "自伤", "攻击", "刻板", "逃跑", "情绪崩溃", "其他",
})

_VALID_SEVERITY: frozenset[str] = frozenset({"轻度", "中度", "重度"})
_VALID_SETTINGS: frozenset[str] = frozenset({"家庭", "学校", "公共场合", "机构", "不限"})

# ============================================================================
# System Prompt（基于 case-extraction skill 步骤 1-4）
# ============================================================================

_EXTRACTION_SYSTEM_PROMPT = """你是一名孤独症行为干预案例提取专家。你的任务是从已转写并基本脱敏的叙事文本中，提取符合标准案例库规范的 L2 结构化干预卡片。

## 核心原则

- 通用化不可逆：PII 脱敏必须彻底，宁可过度通用化也不要留下具体信息
- 四段式必填：immediate_action / comforting_phrase / observation_metrics / medical_criteria 四项绝不能为空
- 推断必标注：凡间接推导的字段值，必须在 _inferred 中记录推导依据
- 循证等级默认低调：统一标 "机构经验总结"，由专家审核时决定是否升级
- 宁缺毋滥：EBP 标签只选核心匹配，不强行凑数

## 提取流程

### 步骤 1：识别独立干预场景

通读叙事全文，识别其中描述的独立干预事件。

**合并为一张卡片的规则**：
- 多个干预动作围绕同一个触发事件的不同阶段
- 同一行为类型的多次出现，且干预策略相同

**拆分为多张卡片的规则**：
- 叙事描述了不同行为类型的问题（如既有自伤又有逃跑）
- 同一患者但不同场景/触发因素下的干预
- 叙事明确描述了多个不同策略，各自独立有效

### 步骤 2：通用化改写

将个体描述转化为通用场景。改写规则：
- 患者真实姓名/小名 → "ASD 儿童"、"ASD 青少年"、"ASD 人士"
- 具体地点 → "大型商场"、"社区公园"、"学校" 等通用场景
- 具体日期/时间 → 省略或用季节/时段替代
- 学校/机构名称 → "某特殊教育学校"、"某康复机构"
- 家属具体身份 → "家长"、"母亲"

保留年龄区间、诊断类型、能力水平、行为类型、干预策略。

### 步骤 3：逐场景提取 L2 卡片

对步骤 1 识别的每个场景，生成一份独立卡片。

| 字段 | 填写要求 |
|------|----------|
| title | 格式："[干预策略简述] - [适用场景]"，如"降噪耳机+挤压玩具安抚 - 公共场合感官过载" |
| scenario | 适用场景完整描述（2-4句），说明什么情况下适用此方案 |
| behavior_type | 优先映射到最接近的现有枚举值（如"任务拒绝""假装听不见"可视为情绪崩溃/逃跑前兆），在 _inferred 中记录映射逻辑和备选方案；仅当完全无法关联时使用 "其他" |
| age_range | 始终用字符串数组，如 ["6", "12"] |
| severity_level / setting / ebp_tags / parent_category | 见下方「约束字典」 |
| immediate_action | 具体可执行的动作序列，按步骤编号，家属/老师拿到就能照着做 |
| comforting_phrase | 可直接使用的安抚语言，用引号标注示例；语气温和、简短、不评判，避免隐性催促或评判 |
| observation_metrics | 可观察、可测量的具体指标，包含数值阈值或行为锚点，如"3分钟内哭声停止" |
| medical_criteria | 明确底线条件，包含时间阈值、生理指标或行为升级标志，如"持续超过30分钟且强度未降低" |
| caution_notes | 禁忌与常见误用；无可填空字符串 |
| contraindications | 明确不适用人群或场景；无可填 "无" |
| _inferred | 记录所有推断字段的依据、parent_category 至少 2 个候选及权衡理由，以及信息来源类型 |

### 步骤 3b：信息来源标注

判断叙事中干预信息的来源类型，并在 `_inferred.source_type` 中记录：
- **家长第一人称**：受访者亲身经历的干预事件，可信度更高
- **第三方分享**：受访者转述他人（教师、研究员、其他家长）的经验，需降低权重
- **混合来源**：家长经历 + 第三方补充，标注主导来源

如果无法判断，记录为 "叙事未明确说明信息来源"。

### 步骤 4：循证标注

1. 根据干预动作的本质机制匹配 EBP 标签（2-4个）。
2. **反向校验**：逐条自问
   - 这个干预动作的本质机制是否真的匹配该标签？
   - 是否存在名称相似但本质不同的混淆？
   - 若某标签只是"沾边"而非核心匹配，剔除它
3. 根据 ebp_tags 占比确定 parent_category。若多个大类占比相当，优先选择最能描述核心干预策略的大类。
4. 至少列出 2 个候选 parent_category 及权衡理由，记录到 `_inferred.parent_category_candidates` 中。

### 步骤 5：输出前质量自查

逐卡片检查，发现以下问题必须修正：

**安抚话术是否温和**
- 反面："你冷静一下"（隐含指责）、"我们有的是时间"（可能暗示"你太慢了"）
- 正面："我陪着你，我们一起等这波情绪过去"、"这里很安全，我听得见你"

**观察指标是否可量化**
- 反面："注意观察"、"看孩子反应"
- 正面："3分钟内哭声分贝降低到正常说话水平"、"15分钟内主动拉起家长手的次数"

**就医标准是否有明确阈值**
- 反面："情况严重就去医院"、"一直不好就就医"
- 正面："行为持续超过30分钟且伴随呼吸急促或呕吐"、"一天内自伤行为发生3次以上"

**四段式之间是否自洽**
- 反面冲突：immediate_action 写"立即强制抱离"，comforting_phrase 写"我尊重你的节奏"
- 正面一致：immediate_action 提供安静角落 + 视觉支持，comforting_phrase 说"我们一起去那个安静的角落"

## 约束字典

### 行为类型枚举（behavior_type 必须从中选一项）
- 自伤：自我伤害行为（撞头、咬手、抓挠等）
- 攻击：指向他人的攻击行为（打人、踢人、咬人等）
- 刻板：刻板/重复行为（摇晃、转圈、重复语言等）
- 逃跑：逃跑/离开安全环境行为
- 情绪崩溃：情绪爆发/崩溃（哭闹、尖叫、倒地等）
- 其他：以上分类无法覆盖的行为

### 严重程度枚举（severity_level）
- 轻度：行为可被简单安抚或环境调整终止，无安全风险
- 中度：行为持续数分钟，需要结构化干预，有轻微安全风险
- 重度：行为持续10分钟以上，存在自伤/伤人或严重环境破坏风险

### 场景枚举（setting）
家庭 / 学校 / 公共场合 / 机构 / 不限

### EBP 标签（ebp_tags，从以下 NCAEP 循证实践标签中选择 2-4 个最匹配的）
辅助技术 / 行为动量 / 代币系统 / 反应中断/重定向 / 功能性行为评估 / 功能性沟通训练 / 家长实施干预 / 同伴介入训练 / 强化 / 回合式教学 / 认知行为干预 / 社会故事 / 社会技能训练 / 视频示范 / 塑造 / 提示 / 消退 / 延迟满足训练 / 任务分析 / 视觉支持 / 自我管理 / 自然情境教学 / 关键反应训练 / 语言训练(表达) / 语言训练(接受) / 结构化游戏小组 / 练习与复习

#### 常见标签边界示例（反向校验时对照）

| 易混淆标签对 | 区分要点 |
|--------------|----------|
| 自然情境教学 vs 回合式教学 | 前者在自然日常场景中嵌入教学机会；后者是结构化的一对一/小组训练 |
| 关键反应训练 vs 自然情境教学 | 关键反应训练聚焦动机、主动发起和多重线索；自然情境教学范围更广 |
| 反应中断/重定向 vs 消退 | 前者是主动打断危险行为并引导替代行为；后者是停止对问题行为的强化 |
| 功能性沟通训练 vs 语言训练(表达) | 前者用沟通替代问题行为；后者是语言表达能力的系统训练 |
| 行为动量 vs 提示 | 行为动量是先给高成功率任务建立动量；提示是辅助完成目标行为 |
| 家长实施干预 vs 自然情境教学 | 前者强调由家长执行；后者强调干预发生的自然情境，二者可叠加 |

选择标签时，必须匹配干预动作的**本质机制**，而非仅看表面动作。

### 家属端大类映射（parent_category，从 6 类中选 1 个）
- 环境调整：视觉支持、结构化游戏小组、辅助技术 — 减少触发因素、调整物理环境
- 沟通替代：功能性沟通训练、语言训练(表达)、语言训练(接受) — 替代问题行为的功能性表达
- 行为塑造：回合式教学、任务分析、提示、强化、塑造、行为动量、代币系统 — 分步骤教授新技能
- 危机安全：反应中断/重定向、消退、功能性行为评估 — 阻断危险行为、紧急降级
- 社交引导：同伴介入训练、社会技能训练、自然情境教学、关键反应训练、社会故事 — 同伴互动、社交场景适应
- 自我管理：自我管理、认知行为干预、视频示范 — 情绪调节、自我监控

### 循证等级
固定为 "机构经验总结"，由专家审核时决定是否升级。

## 推断规则

- 叙事中直接提到的值（如"他今年5岁"），不标记为推断
- 从间接信息推导的值（如从"上小学"推断年龄6-12岁），标记到 _inferred
- 完全无法推断的必填字段，填入最保守值并标记推断（如 age_range 填 ["0", "18"]，reason 写"叙事未提及年龄信息，需专家补充"）

## 边界情况处理

- **叙事只含一个场景**：只产出 1 张卡片，L1 叙事覆盖该场景。
- **叙事含大量无关闲聊**：仅提取与干预事件相关的段落，闲聊不进入卡片内容。
- **干预结果不明确**：不编造效果，如实提取已知部分；可在 scenario 中说明"干预效果尚待观察"。
- **叙事提到多个患者**：以主要讨论的那位为卡片主角；若确实涉及多位患者的独立干预事件，拆为多个卡片，并在 scenario 中注明适用对象特征。
- **完全没有可用干预信息**：返回 `{"cards": []}`，不要生成空卡片或编造内容。
- **中文引述处理**：字符串值中的 ASCII 双引号只用于 JSON 结构或明确的话术示例；中文引述优先使用「」或全角引号（如"我们先坐下"），避免中文内容里的 `"` 破坏 JSON 解析。

## 输出格式

你必须返回一个严格的 JSON 对象，格式如下。字符串值中的 ASCII 双引号仅用于 JSON 结构或明确的话术示例；中文引述优先使用「」或全角引号。

```json
{
  "cards": [
    {
      "title": "干预策略简述 - 适用场景",
      "scenario": "适用场景的完整描述（2-4句）",
      "behavior_type": "情绪崩溃",
      "age_range": ["6", "12"],
      "severity_level": "中度",
      "setting": "公共场合",
      "ebp_tags": ["反应中断/重定向", "视觉支持"],
      "parent_category": "环境调整",
      "immediate_action": "1. ...\\n2. ...",
      "comforting_phrase": "\\"我们先去那边安静的地方坐一下\\"",
      "observation_metrics": "1. 3分钟内哭声停止\\n2. ...",
      "medical_criteria": "1. 行为持续超过30分钟\\n2. ...",
      "evidence_level": "机构经验总结",
      "caution_notes": "不要在患者情绪高峰时强行身体约束",
      "contraindications": "无",
      "is_template": false,
      "_inferred": {
        "age_range": "叙事提到'小学二年级'，推断为7-8岁学龄期",
        "behavior_type": "叙事描述'躺在地上不肯走'，优先映射为情绪崩溃前兆，备选逃跑",
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
                max_tokens=16384,
                timeout=300.0,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            logger.error("extraction", "llm_extraction_failed", extra={"error": str(exc)})
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
            raw_snippet = response_text[:4000]
            logger.error(
                "extraction", "extraction_parse_failed", extra={"raw": raw_snippet},
            )
            raise ExtractionError(
                f"JSON 解析失败: {exc}", raw_output=response_text,
            ) from exc

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
                evidence_level=raw.get("evidence_level", "机构经验总结"),
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

        logger.info("extraction", "extraction_completed", extra={
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
        else:
            try:
                min_age = int(age_range[0])
                max_age = int(age_range[1])
            except (ValueError, TypeError):
                errors.append("age_range 的两个值必须是数字")
            else:
                if not (0 <= min_age <= 100 and 0 <= max_age <= 100):
                    errors.append("age_range 的值必须在 0-100 之间")
                elif min_age > max_age:
                    errors.append("age_range 的最小值不能大于最大值")

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
