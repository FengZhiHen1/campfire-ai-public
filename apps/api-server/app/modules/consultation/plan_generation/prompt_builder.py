"""CSLT-03 应急方案生成 — Prompt 构建器。

提供 PromptBuilder 类，负责将 EmergencyPlanInput 中的结构化数据
组装为 LLM 可消费的 messages 列表（System Prompt + User Message）。

核心职责：
1. System Prompt 构建：角色设定、JSON 输出结构、引用规则、零幻觉约束
2. 参考案例 Markdown 区域构建：预编号、循证等级标注、降序排列
3. 患者档案 Markdown 格式化
4. PII 二次扫描（正则检测手机号和身份证，记录 ALERT 日志）
5. User Message 组装：档案摘要 + 行为描述 + 检索降级提示
"""

from __future__ import annotations

import re
from py_logger import logger

from .models import EmergencyPlanInput, PromptBuildContext

# ============================================================================
# 常量
# ============================================================================

# PII 检测正则（二次安全扫描）
_PHONE_PATTERN: re.Pattern[str] = re.compile(r"1[3-9]\d{9}")
_ID_CARD_PATTERN: re.Pattern[str] = re.compile(r"\d{17}[\dXx]")

# 档案最近事件截断上限（意图文档 §1.6.1 约束）
_MAX_RECENT_EVENTS: int = 5


# ============================================================================
# System Prompt 模板
# ============================================================================

_SYSTEM_PROMPT_TEMPLATE: str = (
    "你是一名孤独症行为干预顾问，擅长为孤独症（ASD）及相关发育障碍患者"
    "的家属提供循证的、可操作的应急行为干预建议。\n\n"
    "## 输出格式要求（最高优先级，必须严格遵守）\n"
    "你的回复必须是一个合法的 JSON 对象，除此之外不输出任何字符——"
    "包括解释、问候语、空白行、Markdown 代码块标记（```）一律禁止。\n\n"
    "**正确输出（首个字符必须是左花括号，最后一个字符必须是右花括号）**：\n"
    '{"即时安全干预动作":["措施1[1]","措施2"],"情绪安抚话术":["话术1","话术2"],"后续观察指标":["指标1","指标2"],"就医判断标准":["标准1","标准2"]}\n\n'
    "**严禁输出（以下格式均为错误）**：\n"
    "- 以 ```json 或 ``` 开头或结尾\n"
    "- 在 JSON 前加任何说明文字（如「好的，以下是方案：」）\n"
    "- 在 JSON 后加任何补充说明\n"
    "- 输出非 JSON 的自然语言回复\n\n"
    "JSON 结构规范：\n"
    "{\n"
    '  "即时安全干预动作": ["具体可操作的安全措施 1 [N]", "措施 2 [N]"],\n'
    '  "情绪安抚话术": ["安抚语句 1", "安抚语句 2"],\n'
    '  "后续观察指标": ["需要观察的指标 1", "指标 2"],\n'
    '  "就医判断标准": ["必须立即就医的情况 1", "可预约门诊的情况 2"]\n'
    "}\n\n"
    "**字段要求**：\n"
    "- 四个字段缺一不可，值为字符串数组\n"
    "- 每个数组至少包含 2 条、至多 5 条建议\n"
    "- 每条建议为一句完整的中文，禁止在建议文本中使用 Markdown 格式\n"
    "- 同一段落内的建议按优先级从高到低排列\n\n"
    "## 危机等级分层策略\n"
    "生成方案时必须结合本次判定的危机等级（mild/moderate/severe）：\n"
    "- mild（轻度）：以家庭现场干预和情绪安抚为主，就医判断标准侧重「观察后仍不缓解再就医」\n"
    "- moderate（中度）：在家庭干预基础上增加明确的观察指标和就医准备，给出清晰的升级触发条件\n"
    "- severe（重度）：优先确保人身安全，立即移除危险因素，就医判断标准必须包含「立即就医/拨打急救电话」\n\n"
    "## 引用规则\n"
    "- 无参考案例时，必须在「即时安全干预动作」的第一条建议中明确告知：当前无匹配的真实干预案例参考，以下建议基于通用专业知识\n\n"
    "## 患者档案感知约束\n"
    "- 必须结合患者档案中的年龄、诊断类型、主要行为、感官特征和触发因素生成建议\n"
    "- 如果行为描述与档案中的历史事件高度相似，优先复用档案中有效的干预经验\n"
    "- 如果行为描述与档案中的触发因素明显冲突，忽略冲突信息并基于当前行为描述生成\n\n"
    "## 零幻觉约束\n"
    "- **仅基于**提供的参考案例上下文和患者档案信息回答\n"
    "- 不得编造案例、研究、数据、药物名称或引用不存在的参考文献\n"
    "- 不得给出医学诊断，不得推荐具体药物剂量\n"
    "- 如果参考案例不足以支撑某个建议，应明确说明「根据通用干预原则」而非假装有案例支持\n\n"
    "## 确定性与语气约束\n"
    "- 生成内容保持高度确定性，给出明确的行为指引而非模棱两可的建议\n"
    "- 使用「请」「建议」「需要」等指导性语气，避免「可以试试」「或许」「可能有用」等弱表述\n"
    "- 对于必须由医生判断的事项，使用「建议尽快咨询医生」而非自行给出诊断\n\n"
)

# 参考案例区域模板（有案例时）
_CASE_BLOCK_TEMPLATE: str = (
    "## 参考案例（共 {count} 条，按匹配度降序）\n"
    "{slices}\n"
)

# 参考案例区域模板（无案例时）
_NO_CASE_BLOCK: str = (
    "**注意**：当前暂无与您描述情况相匹配的真实干预案例参考。"
    "以下建议基于通用专业知识生成，建议咨询专业医生或特教老师获取更具针对性的指导。\n"
)


class PromptBuilder:
    """Prompt 构建器。

    将 EmergencyPlanInput 组装为 LLM messages 列表。
    每次调用 build() 生成新的 Prompt 和 PromptBuildContext。

    Usage:
        builder = PromptBuilder()
        messages, ctx = builder.build(input_data)
    """

    def build(self, input_data: EmergencyPlanInput) -> tuple[list[dict[str, str]], PromptBuildContext]:
        """构建完整的 Prompt messages 列表。

        Args:
            input_data: 校验通过的 EmergencyPlanInput 实例。

        Returns:
            (messages, ctx) 元组：
                messages: OpenAI 格式的 messages 列表，含 system 和 user 两条消息。
                ctx: PromptBuildContext 上下文，包含预编号映射和案例引用信息，
                     供后续步骤（流式收尾、引用反查）使用。
        """
        # 步骤 1：构建参考案例 Markdown 区域
        case_block, ctx = self._build_case_reference(input_data)

        # 步骤 2：构建 System Prompt + 案例区域
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.strip()
        if ctx.has_cases:
            system_prompt += "\n\n" + case_block
        else:
            system_prompt += "\n\n" + _NO_CASE_BLOCK
            system_prompt += (
                "\n\n"
                "**重要额外指令**：当前无参考案例可供引用，因此你的回答中不得包含任何 [N] 格式的来源引用标记。"
                "同时必须在「即时安全干预动作」的第一条建议中说明：当前无匹配的真实干预案例参考，以下建议基于通用专业知识。"
            )

        # 步骤 3：构建 User Message
        user_message = self._build_user_message(input_data, ctx)

        # 步骤 4：PII 二次扫描（不阻断执行，仅记录 ALERT 日志）
        self._scan_pii(input_data, system_prompt + user_message)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        return messages, ctx

    def _build_case_reference(self, input_data: EmergencyPlanInput) -> tuple[str, PromptBuildContext]:
        """构建参考案例 Markdown 区域及预编号映射。

        按 composite_score 降序遍历 search_result.results，
        为每条切片分配预编号（[1]， [2]， ...），
        构建 Markdown 格式的参考案例文本块。

        Args:
            input_data: EmergencyPlanInput 实例。

        Returns:
            (case_markdown, ctx) 元组：
                case_markdown: 参考案例区域的 Markdown 文本。
                ctx: 包含预编号映射和案例数量信息。
        """
        slices = input_data.search_result.results

        if not slices:
            return "", PromptBuildContext(
                prenumbered_slices=[],
                slice_text_block="",
                profile_markdown=input_data.profile_summary,
                has_cases=False,
            )

        # 按 composite_score 降序排列
        sorted_slices = sorted(slices, key=lambda s: s.composite_score, reverse=True)

        prenumbered: list[tuple[str, str]] = []
        slice_lines: list[str] = []

        for i, s in enumerate(sorted_slices, start=1):
            number_tag = f"[{i}]"
            prenumbered.append((number_tag, s.slice_id))

            case_title = s.case_title or "无标题"
            case_date = s.case_created_at or "未知日期"
            evidence = s.evidence_level.value if hasattr(s.evidence_level, "value") else str(s.evidence_level)

            slice_text = s.slice_text or ""

            slice_lines.append(
                f"{number_tag} [{s.card_id}] {case_title}（{case_date}，循证等级：{evidence}）"
            )
            slice_lines.append(f"{slice_text}\n")

        slice_text_block = _CASE_BLOCK_TEMPLATE.format(
            count=len(sorted_slices),
            slices="\n".join(slice_lines),
        )

        ctx = PromptBuildContext(
            prenumbered_slices=prenumbered,
            slice_text_block=slice_text_block,
            profile_markdown=input_data.profile_summary,
            has_cases=True,
        )

        return slice_text_block, ctx

    def _build_user_message(self, input_data: EmergencyPlanInput, ctx: PromptBuildContext) -> str:
        """构建 User Message 内容。

        包含危机等级提示（由上游规则判定产生）、患者档案摘要、行为描述、可选的检索降级提示。

        Args:
            input_data: EmergencyPlanInput 实例。
            ctx: PromptBuildContext 上下文。

        Returns:
            User Message 文本字符串。
        """
        parts: list[str] = []

        # 危机等级提示（由上游 CSLT-01 规则判定产生，severe 已在编排层阻断，不会进入此处）
        final_level = input_data.crisis_result.final_level.value
        parts.append(f"## 当前危机等级\n{final_level}")

        # 患者档案区域
        parts.append("\n## 患者档案\n")
        parts.append(ctx.profile_markdown if ctx.profile_markdown else "（无档案信息）")

        # 当前行为描述
        parts.append("\n## 当前行为描述\n")
        parts.append(input_data.behavior_description)

        # 检索降级提示（如果检索精度降低）
        degradation_note = self._build_degradation_note(input_data)
        if degradation_note:
            parts.append(f"\n## 检索精度说明\n{degradation_note}")

        # 档案结合提醒
        parts.append(
            "\n## 生成要求\n"
            "请结合上述患者档案（年龄、诊断类型、感官特征、触发因素）和当前行为描述，"
            "按当前危机等级生成对应的应急方案。务必优先保证患者和周围人员的安全。"
        )

        return "\n\n".join(parts)

    def _build_degradation_note(self, input_data: EmergencyPlanInput) -> str | None:
        """构建检索降级提示文本。

        当 search_result.degradation_applied=true 时，
        在 User Message 中注入降级说明，告知用户检索精度可能降低。

        Args:
            input_data: EmergencyPlanInput 实例。

        Returns:
            降级提示文本，如无降级则返回 None。
        """
        if not input_data.search_result.degradation_applied:
            return None

        degradation_level = input_data.search_result.degradation_level.value if hasattr(
            input_data.search_result.degradation_level, "value"
        ) else str(input_data.search_result.degradation_level)

        level_hints = {
            "NONE": None,
            "EMOTION_RELAXED": "已放宽情绪等级过滤条件",
            "BEHAVIOR_RELAXED": "已放宽行为类型过滤条件",
            "ALL_TAGS_REMOVED": "已移除全部标签过滤条件",
        }

        hint = level_hints.get(degradation_level, f"已触发降级策略（{degradation_level}）")
        if hint is None:
            return None

        return (
            "**注意**：当前检索因匹配案例数量不足，已自动放宽过滤条件"
            f"（{hint}）。参考案例的相关性可能低于预期，请在使用时注意甄别。"
        )

    def _scan_pii(self, input_data: EmergencyPlanInput, full_text: str) -> None:
        """对 Profile Summary 和 Behavior Description 做 PII 二次扫描。

        使用正则检测手机号（1[3-9]\\d{9}）和身份证号（\\d{17}[\\dXx]）格式。
        注：上游已完成 PII 脱敏，此扫描为二次安全保障，不阻断执行。

        Args:
            input_data: EmergencyPlanInput 实例。
            full_text: 包含 system prompt 和 user message 的全量文本。
        """
        phone_matches = _PHONE_PATTERN.findall(full_text)
        id_matches = _ID_CARD_PATTERN.findall(full_text)

        if phone_matches or id_matches:
            logger.critical(
                service="emergency_plan_generation",
                message="PII detected in prompt text (secondary scan)",
                op_type="pii_scan",
                extra={
                    "trace_id": input_data.request_id,
                    "phone_count": len(phone_matches),
                    "id_card_count": len(id_matches),
                    "request_id": input_data.request_id,
                },
            )
