"""案例入库契约：manifest 与 L2 卡片的值域校验（公共案例库第 4、6 节）。

职责：定义案例包的入库形状（manifest）与其校验、定义卡片的值域与「缺失即拒绝」判定。
边界：只做校验与解析，不写库、不切分、不嵌入——写库归 `case_ingestion`。
参考：docs/技术设计/technical-details/公共案例库.md 第 3、4、6 节；细节见 `validate_manifest`、`validate_card` 的 docstring。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: 上游 L2 卡片的值域（公共案例库第 4 节「值域不重写」：全部沿用上游
#: `references/ebp_reference.md` 的定义，导入校验器直接复用 `validate_l2.py` 的约束）。
#:
#: 为什么在这里再写一份而不是 import 上游脚本：上游是链外的本地转写工具
#: （FunASR 转写 + 抽取，不进本仓库依赖，第 6 节），生产代码 import 它会让摄取依赖一个
#: 版本不受控的外部目录。因此按上游脚本逐条转写约束，并在测试里用上游导出的真实
#: 卡片与越界值双向锁定（见 `tests/test_library_case_schema.py`）。
BEHAVIOR_TYPES: frozenset[str] = frozenset({"自伤", "攻击", "刻板", "逃跑", "情绪崩溃", "其他"})
SEVERITY_LEVELS: frozenset[str] = frozenset({"轻", "中", "重"})
SETTINGS: frozenset[str] = frozenset({"家庭", "学校", "公共场合", "机构", "不限"})
PARENT_CATEGORIES: frozenset[str] = frozenset({"环境调整", "沟通替代", "行为塑造", "危机安全", "社交引导", "自我管理"})
CARD_EVIDENCE_LEVELS: frozenset[str] = frozenset({"EBP", "INSTITUTIONAL", "OBSERVATIONAL"})

#: NCAEP 2020 的 28 项 EBP 标签（上游 `validate_l2.py` 的完整清单，中文名(缩写)）。
#:
#: 证据边界（公共案例库「已知偏差」）：清单与中文译名抄自上游 `ebp_reference.md`，
#: 本项目未独立核验 NCAEP 原文（其中 23–28 项上游自称补充项）。此处照搬，
#: 不自行增删——擅自改动会让原本合格的包被判失败。
VALID_EBP_TAGS: frozenset[str] = frozenset(
    {
        "前因干预(ABI)",
        "辅助替代沟通(AAC)",
        "行为动力干预(BMI)",
        "认知行为策略(CBI)",
        "差别强化(DR)",
        "直接教学(DI)",
        "离散试教学(DTT)",
        "消退(EXT)",
        "功能行为评估(FBA)",
        "功能沟通训练(FCT)",
        "自然主义干预(NI)",
        "家属实施干预(PII)",
        "同伴教学(PBI)",
        "提示(PP)",
        "强化(R)",
        "反应中断/重定向(RIR)",
        "自我管理(SM)",
        "社交叙事(SN)",
        "社交技能训练(SST)",
        "任务分析(TA)",
        "视频示范(VM)",
        "视觉支持(VS)",
        "运动与锻炼(Exercise)",
        "功能沟通(Functional Communication)",
        "示范(Modeling)",
        "音乐辅助干预(Music-Mediated Intervention)",
        "感觉统合(Sensory Integration)",
        "技术辅助干预(Technology-Aided Intervention)",
    }
)

#: 卡片的必填字符串字段（上游 `validate_l2.py` 的 14 项，逐条转写）。
#:
#: `card_id` / `raw_id` 在上游是 `{AWAITING_SYSTEM}` 占位符——我们侧由系统分配
#: （第 4 节：`card_id` 规则 `<external_key>#<NN>`），因此校验时不要求它们
#: 已填具体值，只要求键存在（占位符与真值都接受，见 `validate_card`）。
REQUIRED_CARD_STRINGS: tuple[str, ...] = (
    "card_id",
    "raw_id",
    "title",
    "scenario",
    "behavior_type",
    "severity_level",
    "setting",
    "parent_category",
    "immediate_action",
    "comforting_phrase",
    "observation_metrics",
    "medical_criteria",
    "evidence_level",
    "caution_notes",
)
#: 必填数组字段。
REQUIRED_CARD_ARRAYS: tuple[str, ...] = ("age_range", "ebp_tags")
#: 必填布尔字段。
REQUIRED_CARD_BOOLS: tuple[str, ...] = ("is_template",)
#: 可选字符串字段（可为空串，但给了就必须是字符串）。
OPTIONAL_CARD_STRINGS: tuple[str, ...] = ("contraindications",)
#: 可选对象字段（推断依据）。
OPTIONAL_CARD_OBJECTS: tuple[str, ...] = ("_inferred",)

#: 卡片不参与嵌入的字段（RAG 策略第 1.3 节）：
#: - `_inferred`：推断依据不应驱动命中（公共案例库第 4 节「不参与检索注入」）；
#: - 标识字段：`card_id`/`case_id` 无检索语义，嵌入它们只会引入噪声。
CARD_NON_EMBEDDED_FIELDS: frozenset[str] = frozenset({"card_id", "case_id", "raw_id", "_inferred"})

#: manifest 的必填字段（公共案例库第 6 节）。`reviewer` 明确可为 null（三档语义），
#: 故它是必填键但允许空值；`files` 是必填的嵌套对象。
MANIFEST_REQUIRED_FIELDS: tuple[str, ...] = (
    "external_key",
    "title",
    "source_type",
    "subject_type",
    "interview_at",
    "consent_scope",
    "evidence_level",
    "review_status",
    "authorization",
    "files",
)
#: manifest 中允许为 null 的必填键。
MANIFEST_NULLABLE_FIELDS: frozenset[str] = frozenset({"reviewer", "consent_recorded_at"})
#: `files` 的必填键；`review_report` 可选（它只是人工阅读附件，不参与检索）。
MANIFEST_FILE_KEYS: tuple[str, ...] = ("narrative", "cards")

#: 一期只有一种来源类型（公共案例库第 3 节）。
SOURCE_TYPE_INTERVIEW = "专家访谈转写"

#: 一期同意范围固定值（第 3、5 节：用户 2026-09-29 确认覆盖到 AI 检索与建议）。
CONSENT_SCOPE_AI_RETRIEVAL = "ai_retrieval_and_advice"


class CasePackageError(Exception):
    """案例包不合法：manifest 缺字段、卡片越界或引用的文件不存在。

    整包拒绝，不做部分导入（公共案例库第 6 节）——半个案例比没有案例更危险：
    它会以「已入库」的身份进入检索，而缺少的那部分无人知晓。
    """


@dataclass(frozen=True, slots=True)
class CaseManifest:
    """一个案例包的 manifest（公共案例库第 6 节的形状）。"""

    external_key: str
    title: str
    source_type: str
    subject_type: str
    interview_at: datetime
    consent_scope: str
    evidence_level: str
    review_status: str
    authorization: str
    narrative_file: str
    card_files: tuple[str, ...]
    review_report_file: str | None = None
    reviewer: str | None = None
    consent_recorded_at: str | None = None
    transcript_ref: str | None = None
    keywords: str = ""
    aliases: str = ""
    status: str = "internal"

    def card_id_for(self, index: int) -> str:
        """按第 4 节规则生成卡片标识：`<external_key>#<NN>`（两位数）。"""
        return f"{self.external_key}#{index:02d}"


def _require_str(payload: dict[str, object], key: str, *, context: str) -> str:
    """取必填字符串字段。

    Raises:
        CasePackageError: 键缺失、不是字符串或为空串。
    """
    if key not in payload:
        raise CasePackageError(f"{context} 缺少必填字段：{key}")
    value = payload[key]
    if not isinstance(value, str):
        raise CasePackageError(f"{context} 的 {key} 应为字符串，实际 {type(value).__name__}")
    if not value.strip():
        raise CasePackageError(f"{context} 的 {key} 不能为空")
    return value


def parse_interview_at(value: str) -> datetime:
    """解析访谈时间为带时区的 `datetime`。

    「什么时候」是三个必答问题之一（公共案例库第 1 节），因此格式错误即拒绝导入，
    不做「解析不出就留空」的静默兜底——留空等于让该案例无法回答何时发生。

    Raises:
        CasePackageError: 不是 ISO 8601 格式，或缺少时区偏移。
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CasePackageError(f"interview_at 不是 ISO 8601 时间：{value!r}") from exc
    if parsed.tzinfo is None:
        # 无时区的访谈时间无法与「现在」比较，也无法跨时区解释；上游目录名带 +08:00。
        raise CasePackageError(f"interview_at 缺少时区偏移：{value!r}")
    return parsed


def _require_domain(value: str, allowed: frozenset[str], field: str) -> None:
    """校验一个字段的取值落在给定位域内。

    Raises:
        CasePackageError: 取值越界。错误信息带字段名与合法值，便于改包。
    """
    if value not in allowed:
        raise CasePackageError(f"{field} 无效值：{value!r}，合法值：{sorted(allowed)}")


def _validate_case_domains(*, subject_type: str, evidence_level: str, review_status: str, reviewer: object) -> None:
    """校验案例专属字段的取值域与「具名审阅者」判据。

    值域与条目表的 CHECK 同源（`models.py` 的常量），但在入口先拒——
    让错误在「读文件」阶段暴露，带上出错的字段名，而不是落库时抛一个
    CheckViolation 让人去猜哪一行有问题。

    Raises:
        CasePackageError: 值域越界，或 `reviewer` 与 `review_status` 不匹配。
    """
    # 延迟导入：`models` 与 `case_schema` 同属 library 模块，但 models 是表结构、
    # case_schema 是入库契约，顶层互引会在迁移与校验之间绕出一个循环导入。
    from campfire.modules.library.models import EVIDENCE_LEVELS, REVIEW_STATUSES, SUBJECT_TYPES

    _require_domain(subject_type, SUBJECT_TYPES, "subject_type")
    _require_domain(evidence_level, EVIDENCE_LEVELS, "evidence_level")
    _require_domain(review_status, REVIEW_STATUSES, "review_status")

    # reviewer 的必填判据与表上的 CHECK 同源（第 7 节）：具名审阅者只在 professional 档。
    # 对称校验：owner/pending 出现具名审阅者会把「项目所有者核准」冒充成专业审阅。
    if review_status == "professional" and not reviewer:
        raise CasePackageError("review_status = professional 时必须提供具名 reviewer")
    if review_status != "professional" and reviewer:
        raise CasePackageError(f"review_status = {review_status} 时不得填 reviewer——那会把项目所有者核准冒充成专业审阅")
    if reviewer is not None and not isinstance(reviewer, str):
        raise CasePackageError(f"reviewer 应为字符串或 null，实际 {type(reviewer).__name__}")


def _parse_files(files: object, context: str) -> tuple[str, tuple[str, ...], str | None]:
    """校验 manifest 的 `files` 块，返回 `(narrative, cards, review_report)`。

    Raises:
        CasePackageError: `files` 不是对象、缺必填键、或条目形状不合法。
    """
    if not isinstance(files, dict):
        raise CasePackageError(f"{context} 的 files 应为对象，实际 {type(files).__name__}")
    for key in MANIFEST_FILE_KEYS:
        if key not in files:
            raise CasePackageError(f"{context} 的 files 缺少必填键：{key}")

    narrative_file = files["narrative"]
    if not isinstance(narrative_file, str) or not narrative_file.strip():
        raise CasePackageError("files.narrative 应为非空字符串")

    raw_cards = files["cards"]
    if not isinstance(raw_cards, list) or not raw_cards:
        raise CasePackageError("files.cards 应为非空数组（案例必须至少含一张卡片）")
    card_files: list[str] = []
    for index, entry in enumerate(raw_cards):
        if not isinstance(entry, str) or not entry.strip():
            raise CasePackageError(f"files.cards[{index}] 应为非空字符串")
        card_files.append(entry)

    # review_report 可选：它只是人工阅读附件，不参与检索（第 2、6 节）。
    review_report = files.get("review_report")
    if review_report is not None and (not isinstance(review_report, str) or not review_report.strip()):
        raise CasePackageError("files.review_report 应为非空字符串或省略")

    return narrative_file, tuple(card_files), review_report


def load_manifest(path: Path) -> CaseManifest:
    """读取并校验案例包的 `manifest.json`。

    上游把元数据写在 `L1_*.md` 的页脚里、机器不可读（第 6 节），因此 manifest
    是必须补的一环。缺失或非法即整包拒绝，不做部分导入。

    Raises:
        CasePackageError: 文件不存在、JSON 非法或字段不满足契约。
    """
    if not path.is_file():
        raise CasePackageError(f"缺少 manifest.json：{path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CasePackageError(f"manifest.json 不是合法 JSON：{exc.msg}") from exc
    except OSError as exc:
        raise CasePackageError(f"读取 manifest.json 失败：{type(exc).__name__}") from exc

    if not isinstance(payload, dict):
        raise CasePackageError("manifest.json 的根节点必须是 JSON 对象")

    context = "manifest.json"
    for key in MANIFEST_REQUIRED_FIELDS:
        if key not in payload:
            raise CasePackageError(f"{context} 缺少必填字段：{key}")

    external_key = _require_str(payload, "external_key", context=context)
    title = _require_str(payload, "title", context=context)
    source_type = _require_str(payload, "source_type", context=context)
    subject_type = _require_str(payload, "subject_type", context=context)
    consent_scope = _require_str(payload, "consent_scope", context=context)
    evidence_level = _require_str(payload, "evidence_level", context=context)
    review_status = _require_str(payload, "review_status", context=context)
    authorization = _require_str(payload, "authorization", context=context)
    interview_at = parse_interview_at(_require_str(payload, "interview_at", context=context))

    _validate_case_domains(
        subject_type=subject_type,
        evidence_level=evidence_level,
        review_status=review_status,
        reviewer=payload.get("reviewer"),
    )

    narrative_file, card_files, review_report = _parse_files(payload["files"], context)

    consent_recorded_at = payload.get("consent_recorded_at")
    if consent_recorded_at is not None and not isinstance(consent_recorded_at, str):
        raise CasePackageError(f"consent_recorded_at 应为字符串或 null，实际 {type(consent_recorded_at).__name__}")

    return CaseManifest(
        external_key=external_key,
        title=title,
        source_type=source_type,
        subject_type=subject_type,
        interview_at=interview_at,
        consent_scope=consent_scope,
        evidence_level=evidence_level,
        review_status=review_status,
        authorization=authorization,
        narrative_file=narrative_file,
        card_files=card_files,
        review_report_file=review_report,
        reviewer=payload.get("reviewer"),
        consent_recorded_at=consent_recorded_at,
        transcript_ref=payload.get("transcript_ref") or None,
        keywords=str(payload.get("keywords") or ""),
        aliases=str(payload.get("aliases") or ""),
        status=str(payload.get("status") or "internal"),
    )


def _validate_card_shape(payload: dict[str, object], card_label: str) -> list[str]:
    """校验卡片的字段在场与类型正确（必填 14 字符串 + 2 数组 + 1 布尔 + 可选字段）。

    形状与取值域分开的原因（CORE-09）：形状错了之后跑枚举校验只会刷出一堆
    误导性的「越界」报错，掩盖真正的首个问题；而两件事的判据来源也不同
    （形状来自上游 schema，取值域来自上游 `ebp_reference.md`）。
    """
    errors: list[str] = []

    for field in REQUIRED_CARD_STRINGS:
        if field not in payload:
            errors.append(f"{card_label} 缺少必填字段：{field}")
            continue
        # 先取出再收窄：`payload[field]` 的键是循环变量，mypy 不把上一条 `elif`
        # 里对 `payload[field]` 的 `isinstance` 结果沿用到下一条分支——重复下标会让
        # 收窄丢失（下标表达式的类型只能按语句推一次）。取值到局部变量后，
        # `isinstance` 的收窄对后续分支成立，空串判定也就看到了 `str`。
        value = payload[field]
        if not isinstance(value, str):
            errors.append(f"{card_label} 的 {field} 应为 string，实际 {type(value).__name__}")
        elif not value.strip():
            errors.append(f"{card_label} 的 {field} 不能为空")

    for field in REQUIRED_CARD_ARRAYS:
        if field not in payload:
            errors.append(f"{card_label} 缺少必填字段：{field}")
        elif not isinstance(payload[field], list):
            errors.append(f"{card_label} 的 {field} 应为 array，实际 {type(payload[field]).__name__}")
        elif not payload[field]:
            errors.append(f"{card_label} 的 {field} 不能为空数组")

    for field in REQUIRED_CARD_BOOLS:
        if field not in payload:
            errors.append(f"{card_label} 缺少必填字段：{field}")
        elif not isinstance(payload[field], bool):
            errors.append(f"{card_label} 的 {field} 应为 boolean，实际 {type(payload[field]).__name__}")

    for field in OPTIONAL_CARD_STRINGS:
        if field in payload and not isinstance(payload[field], str):
            errors.append(f"{card_label} 的 {field} 应为 string，实际 {type(payload[field]).__name__}")

    for field in OPTIONAL_CARD_OBJECTS:
        if field in payload and not isinstance(payload[field], dict):
            errors.append(f"{card_label} 的 {field} 应为 object，实际 {type(payload[field]).__name__}")

    return errors


def _validate_card_domains(payload: dict[str, object], card_label: str) -> list[str]:
    """校验卡片的取值域：五个枚举字段、两个数组元素、`_inferred` 的值类型。

    值域全部沿用上游（公共案例库第 4 节「值域不重写」），因此这里的每个集合
    都能在上游 `validate_l2.py` 里找到同名常量。

    前置：调用方已跑过 `_validate_card_shape`，因此必填字段在场且类型正确。
    这里仍用 `isinstance` 收窄而不是断言类型——类型收窄让「形状校验被绕过」
    退化为「少报几条」，而不是让本函数抛 `TypeError`（边界显式但不脆）。
    """
    errors: list[str] = []

    for field, allowed in (
        ("behavior_type", BEHAVIOR_TYPES),
        ("severity_level", SEVERITY_LEVELS),
        ("setting", SETTINGS),
        ("parent_category", PARENT_CATEGORIES),
        ("evidence_level", CARD_EVIDENCE_LEVELS),
    ):
        if payload.get(field) not in allowed:
            errors.append(f"{card_label} 的 {field} 无效值：{payload.get(field)!r}")

    age_range = payload.get("age_range")
    if isinstance(age_range, list):
        for index, item in enumerate(age_range):
            if not isinstance(item, str):
                errors.append(f"{card_label} 的 age_range[{index}] 应为 string，实际 {type(item).__name__}")

    ebp_tags = payload.get("ebp_tags")
    if isinstance(ebp_tags, list):
        for index, tag in enumerate(ebp_tags):
            if not isinstance(tag, str):
                errors.append(f"{card_label} 的 ebp_tags[{index}] 应为 string，实际 {type(tag).__name__}")
            elif tag not in VALID_EBP_TAGS:
                errors.append(f"{card_label} 的 ebp_tags[{index}] 不在 NCAEP 28 项中：{tag!r}")

    inferred = payload.get("_inferred")
    if isinstance(inferred, dict):
        for key, value in inferred.items():
            if not isinstance(value, str):
                errors.append(f"{card_label} 的 _inferred.{key} 应为 string（推断理由），实际 {type(value).__name__}")

    return errors


def validate_card(payload: object, *, card_label: str) -> list[str]:
    """校验单张 L2 卡片，返回错误清单（空表示通过）。

    约束逐条转写自上游 `validate_l2.py`（必填 14 字符串 + 2 数组 + 1 布尔、
    `contraindications` 可选、`_inferred` 值为字符串、六个枚举字段的取值域），
    理由见模块头部的「值域不重写」。

    Returns:
        错误信息列表；不做部分修正——调用方据非空即整包拒绝（第 6 节）。
    """
    if not isinstance(payload, dict):
        return [f"{card_label} 根节点必须是 JSON 对象"]

    errors = _validate_card_shape(payload, card_label)
    # 必填字段有问题时跳过枚举校验：否则一个缺失字段会连带刷出一堆误导性的越界报错。
    if errors:
        return errors
    return _validate_card_domains(payload, card_label)


def inferred_field_names(payload: dict[str, object]) -> list[str]:
    """从卡片的 `_inferred` 取出被推断字段的键清单（第 4 节）。

    `_inferred` 的每个键都登记进 `inferred_fields`；被推断的字段在输出中必须
    标为推断，不得作为事实。键排序后返回，让入库结果与输入顺序无关（幂等）。
    """
    inferred = payload.get("_inferred")
    if not isinstance(inferred, dict):
        return []
    return sorted(str(key) for key in inferred)


def build_card_embedding_text(payload: dict[str, object]) -> str:
    """按第 1.3 节把卡片拼成嵌入文本：逐字段「字段名：值」，保留字段边界。

    为什么拼接而不是取某个大字段：卡片是结构化 JSON，逐字段拼接保留了字段边界，
    比自由文本拼接的语义命中更准（RAG 策略第 1.3 节）。

    不参与嵌入（`CARD_NON_EMBEDDED_FIELDS`）：`_inferred`（推断依据不应驱动命中）
    与标识字段（无检索语义）。
    """
    parts: list[str] = []
    for key, value in payload.items():
        if key in CARD_NON_EMBEDDED_FIELDS:
            continue
        if isinstance(value, list):
            rendered = "、".join(str(item) for item in value)
        elif isinstance(value, bool):
            # 布尔渲染成中文取值：`is_template: false` 对中文查询没有语义贡献，
            # 而嵌入模型对「否」这类中文词是有区分的。
            rendered = "是" if value else "否"
        else:
            rendered = str(value)
        if rendered.strip():
            parts.append(f"{key}：{rendered}")
    return "\n".join(parts)


__all__ = [
    "BEHAVIOR_TYPES",
    "CARD_EVIDENCE_LEVELS",
    "CARD_NON_EMBEDDED_FIELDS",
    "CONSENT_SCOPE_AI_RETRIEVAL",
    "CaseManifest",
    "CasePackageError",
    "MANIFEST_FILE_KEYS",
    "MANIFEST_REQUIRED_FIELDS",
    "OPTIONAL_CARD_OBJECTS",
    "OPTIONAL_CARD_STRINGS",
    "PARENT_CATEGORIES",
    "REQUIRED_CARD_ARRAYS",
    "REQUIRED_CARD_BOOLS",
    "REQUIRED_CARD_STRINGS",
    "SEVERITY_LEVELS",
    "SETTINGS",
    "SOURCE_TYPE_INTERVIEW",
    "VALID_EBP_TAGS",
    "build_card_embedding_text",
    "inferred_field_names",
    "load_manifest",
    "parse_interview_at",
    "validate_card",
]
