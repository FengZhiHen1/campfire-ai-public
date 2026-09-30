"""案例摄取：把上游案例包（manifest + L1 叙事 + L2 卡片）切分、嵌入、写入。

职责：按公共案例库第 4、6 节读一个案例包，校验后把卡片与叙事写进条目表与节点表（同事务）。
边界：只做摄取，不暴露服务端点；manifest 缺字段或卡片越界整包拒绝，不做部分导入。
参考：docs/技术设计/technical-details/公共案例库.md 第 2、4、6 节；docs/技术设计/technical-details/RAG策略.md 第 1.3、2、7 节；细节见 `ingest_case_package` 的 docstring。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from campfire.core.config import Settings
from campfire.modules.library.case_schema import (
    CARD_EVIDENCE_LEVELS,
    CaseManifest,
    CasePackageError,
    build_card_embedding_text,
    inferred_field_names,
    load_manifest,
    validate_card,
)
from campfire.modules.library.chunking import Chunk, chunk_markdown_section
from campfire.modules.library.embedding import (
    EmbeddingConfigurationError,
    assert_text_within_limit,
)
from campfire.modules.library.ingestion import (
    IngestionError,
    embed_texts,
    parse_frontmatter,
)
from campfire.modules.library.models import (
    LIBRARY_CASE,
    CaseItem,
    RetrievedNode,
)

#: 叙事五节的标题（公共案例库第 3 节：五节叙述作为可检索节点）。
#:
#: 这一节清单来自上游 L1 的固定结构（"场景背景/患者特征/行为表现/干预过程/结果与反思"），
#: 是契约的一部分：分块按它切，`locator` 用它回指，缺一节的叙事会被判为残缺。
NARRATIVE_SECTIONS: tuple[str, ...] = ("场景背景", "患者特征", "行为表现", "干预过程", "结果与反思")

# 卡片节点的 locator = 卡片 `title`（RAG 策略第 1.3 节），回指靠 `card_id`。
# 不加「卡片/」一类前缀——契约写的是「取卡片 title」，前缀会让 locator 与卡片标题
# 不再是同一个事实（按 locator 反查标题就会查不到）。卡片与叙事小节的区分靠节点
# metadata 的 `node_kind`，不靠 locator 拼前缀。


class CaseIngestionError(Exception):
    """案例摄取失败：包不合法、读文件失败、嵌入失败或写库失败。

    与 `IngestionError` 分开：案例包的失败语义是「整包拒绝」（第 6 节），
    而资料摄取是「一份文件一个事务」；把两者混成一个异常类型会让调用方无法
    区分「这个包不合契约」与「库写不进去」。
    """


@dataclass
class CaseIngestionResult:
    """一次案例摄取的结果，供 CLI 输出与导入记账使用。"""

    source_path: str
    item_id: str
    external_key: str
    #: 未变而跳过的包（幂等）：True 时没有写入任何行。
    skipped: bool = False
    #: 写入的卡片数（每张卡片至少一个节点；超长卡片会有多个同 `card_id` 节点）。
    cards_written: int = 0
    #: 写入的叙事节点数（按五节切分）。
    narrative_nodes: int = 0
    #: 因超限且不可分而未嵌入的块数——它们进人工处理队列（不静默截断）。
    needs_manual_review: int = 0
    #: 逐块的定位信息，便于撤下时回溯。
    locators: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _PreparedChunk:
    """一个待写入节点：文本 + 向量 + 完整 metadata。"""

    text: str
    metadata: dict[str, object]


def _compute_package_hash(manifest_path: Path, card_paths: list[Path], narrative_path: Path) -> str:
    """案例包内容哈希，用于幂等判断（未变跳过）。

    为什么哈希覆盖 manifest 与全部卡片、叙事而不是只哈希 manifest：
    上游可能只改了卡片内容（重新抽取）而 manifest 不动，只哈希 manifest 会让
    「内容变了但被跳过」——那是最坏的一类静默：库里留着旧卡片，而运维以为已更新。
    文件名参与哈希，因此「换了一张卡片文件」也算变更。
    """
    digest = hashlib.sha256()
    for path in [manifest_path, narrative_path, *card_paths]:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def _card_metadata(
    manifest: CaseManifest, item_id: str, card: dict[str, object], card_id: str, locator: str
) -> dict[str, object]:
    """卡片节点的 metadata：条目投影 + 结构化过滤维度（RAG 策略第 1.3、2 节）。

    除通用投影（`item_id`/`library`/`status`/`withdrawn`）外，卡片节点按第 2 节的
    案例投影清单再带：

    - 返回契约消费的字段：`source_type`、`evidence_level`、`review_status`、
      `interview_at`、`makes_claims_high_risk`、`inferred_fields`、`authorization`；
    - 聚合依赖：`card_id`；
    - 结构化过滤维度：`risk_class`、`age_range`、`severity_level`、`behavior_type`、
      `ebp_tags`、`parent_category`（案例的「元数据过滤」面）。

    其余字段（`subject_type`、`consent_*`、`transcript_ref`）从窄不投影（第 2 节）。

    `withdrawn` 与 `makes_claims_high_risk` 用字符串存：`MetadataFilter.value`
    的类型联合不含 `bool`（实测）。
    """
    return {
        "item_id": item_id,
        "library": LIBRARY_CASE,
        "status": manifest.status,
        "withdrawn": "false",
        # --- 返回契约消费 ---
        "authorization": manifest.authorization,
        "source_type": manifest.source_type,
        "evidence_level": card["evidence_level"],
        "review_status": manifest.review_status,
        "interview_at": manifest.interview_at.isoformat(),
        "makes_claims_high_risk": "true" if _card_is_high_risk(card) else "false",
        "inferred_fields": inferred_field_names(card),
        # --- 聚合依赖 ---
        "card_id": card_id,
        # --- 结构化过滤维度 ---
        "age_range": card["age_range"],
        "severity_level": card["severity_level"],
        "behavior_type": card["behavior_type"],
        "ebp_tags": card["ebp_tags"],
        "parent_category": card["parent_category"],
        # --- 结构 ---
        "title": card["title"],
        "locator": locator,
        "node_kind": "card",
    }


def _narrative_metadata(
    manifest: CaseManifest, item_id: str, chunk: Chunk, *, makes_claims_high_risk: bool
) -> dict[str, object]:
    """叙事节点的 metadata：同通用投影 + 返回契约字段，但无卡片级维度。

    叙事小节不是卡片（第 2 节：检索单位是卡片、`narrative` 各节也作为可检索节点），
    因此不带 `card_id`/`inferred_fields`（`inferred_fields` 的取值规则就是
    「该结果 snippet 所属卡片」的清单，叙事无卡片可言）。

    高风险标记取案例级判定：叙事常复述含高风险处置的干预过程，
    「命中内容是否含高风险」在叙事命中时同样要如实回答。
    """
    return {
        "item_id": item_id,
        "library": LIBRARY_CASE,
        "status": manifest.status,
        "withdrawn": "false",
        "authorization": manifest.authorization,
        "source_type": manifest.source_type,
        "evidence_level": manifest.evidence_level,
        "review_status": manifest.review_status,
        "interview_at": manifest.interview_at.isoformat(),
        "makes_claims_high_risk": "true" if makes_claims_high_risk else "false",
        "inferred_fields": [],
        "title": manifest.title,
        "locator": chunk.locator,
        "node_kind": "narrative",
    }


#: 高风险字段（公共案例库第 5 节的「高风险」档）。
#:
#: 分级按内容而非仅按字段（第 5 节），最终逐条判断在 skill 层完成；
#: 这里只按字段给出提示与过滤维度（`risk_class` 的定位），不假装成安全边界。
HIGH_RISK_CARD_FIELDS: tuple[str, ...] = ("immediate_action", "medical_criteria", "contraindications", "caution_notes")


def _card_is_high_risk(card: dict[str, object]) -> bool:
    """卡片是否含高风险内容。

    判定口径（第 5 节）：`medical_criteria` 或 `contraindications` 非空即视为高风险
    ——它们直接涉及医疗处置与禁忌，是「不得以祈使句给出」的核心。`caution_notes`
    单独出现不抬高整卡等级（它常是通用提醒），但仍随卡片返回。

    ⚠️ 这只是提示维度，不是安全边界：内容级分级在 skill 层完成，提示词层可被绕过
    （第 5 节明说「不是安全边界」）。真实闸门是 `EVID-A` 与 `EVID-B`。
    """
    for field_name in ("medical_criteria", "contraindications"):
        value = card.get(field_name)
        if isinstance(value, str) and value.strip() and value.strip() != "无":
            return True
    return False


def _case_is_high_risk(cards: list[dict[str, object]]) -> bool:
    """案例级高风险标记：任一卡片含高风险内容即为真。

    为什么要有案例级标记（公共案例库第 5 节）：`makes_claims_high_risk` 为真的案例
    在检索返回时必须带该标记，供 skill 决定呈现方式（转述语而非祈使句）。
    判定放在条目层而不是只在卡片节点上，是因为返回契约的该字段是条目字段——
    它在聚合回案例后仍要可用。
    """
    return any(_card_is_high_risk(card) for card in cards)


def split_narrative(text: str) -> list[Chunk]:
    """把 L1 叙事按五节标题切块。

    为什么不用框架的 `MarkdownNodeParser`：叙事是固定五节的结构（第 3 节），
    按 `#` 层级切会把标题行与正文分开、并产出与五节不一致的 `header_path`，
    而我们要的 `locator` 正是「哪一节」。按已知的五节标题直接切更贴合契约，
    也免去「标题层级写法变了就切错」的脆弱依赖。
    """
    lines = text.splitlines()
    sections: dict[str, list[str]] = {}
    current: str | None = None
    preamble: list[str] = []

    for line in lines:
        heading = _section_heading(line)
        if heading is not None:
            current = heading
            sections.setdefault(current, [])
            continue
        if current is None:
            preamble.append(line)
        else:
            sections[current].append(line)

    chunks: list[Chunk] = []
    index = 0
    for heading in NARRATIVE_SECTIONS:
        body = "\n".join(sections.get(heading, [])).strip()
        if not body:
            continue
        # header_path 传根 "/"、section_title 传节名：`chunk_markdown_section` 的
        # `_join_locator` 是「父级路径 + 当前标题」，若把节名同时当父级路径传进去，
        # `locator` 会拼成 `/场景背景/场景背景/`（重复）。叙事只有一节一层，
        # 父级就是根。
        report = chunk_markdown_section("/", body, start_index=index, section_title=heading)
        chunks.extend(report.chunks)
        index += len(report.chunks)
    return chunks


def _section_heading(line: str) -> str | None:
    """判断一行是否是五节标题，是则返回节名（容忍 `#` 前缀与 `**` 加粗）。

    为什么容忍多种写法：上游 L1 用 `##` 标题，但人工整理的叙事可能写成
    `场景背景`。只认一种写法会让整节被当成正文丢掉（静默丢内容），
    而容忍写法只是多认几行。
    """
    stripped = line.strip()
    if not stripped:
        return None
    candidate = stripped.lstrip("#").strip()
    candidate = candidate.strip("*").strip()
    candidate = candidate.rstrip("：:").strip()
    return candidate if candidate in NARRATIVE_SECTIONS else None


def _assert_cards_within_limits(cards: list[dict[str, object]], card_ids: list[str]) -> None:
    """校验每张卡片的嵌入文本未超嵌入接口硬限。

    超长处理本应复用第 1.2 节规则（第 1.3 节：超 2000 字符按句边界二次切分，
    切出的多个节点同 `card_id`）。一期实测的 10 张卡片最长 1,256 字符，远低于
    2,000 的硬限，因此不做二次切分（不为单一场景建抽象）；但仍显式校验：
    超出时明确失败并指出是哪张卡片，而不是让供应商拒绝或（更糟）被静默截断
    ——截断会制造错误的检索依据。

    Raises:
        CaseIngestionError: 某张卡片的嵌入文本超过 `MAX_TEXT_CHARS`。
    """
    for card, card_id in zip(cards, card_ids, strict=True):
        text = build_card_embedding_text(card)
        try:
            assert_text_within_limit(text)
        except ValueError as exc:
            raise CaseIngestionError(
                f"卡片 {card_id} 的嵌入文本超限（{len(text)} 字符）：{exc}。"
                "按 RAG 策略第 1.3 节需按句边界二次切分并复用同一 card_id，该路径尚未实现"
            ) from exc


def _load_cards(manifest: CaseManifest, package_dir: Path) -> tuple[list[dict[str, object]], list[str], list[Path]]:
    """读取并校验全部卡片，返回 `(卡片, card_id 清单, 文件路径清单)`。

    整包拒绝（第 6 节）：任一张卡片越界即抛错，不做部分导入。

    Raises:
        CaseIngestionError: 卡片文件缺失、JSON 非法或值域越界。
    """
    cards: list[dict[str, object]] = []
    card_ids: list[str] = []
    paths: list[Path] = []

    for index, name in enumerate(manifest.card_files, start=1):
        path = package_dir / name
        if not path.is_file():
            raise CaseIngestionError(f"manifest 引用的卡片文件不存在：{name}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CaseIngestionError(f"卡片 {name} 不是合法 JSON：{exc.msg}") from exc
        except OSError as exc:
            raise CaseIngestionError(f"读取卡片 {name} 失败：{type(exc).__name__}") from exc

        errors = validate_card(payload, card_label=name)
        if errors:
            raise CaseIngestionError("案例包拒绝导入（卡片不合契约）：\n" + "\n".join(errors))

        cards.append(payload)
        card_ids.append(manifest.card_id_for(index))
        paths.append(path)

    return cards, card_ids, paths


async def ingest_case_package(
    settings: Settings,
    session: AsyncSession,
    *,
    vector_store: PGVectorStore,
    package_dir: Path,
) -> CaseIngestionResult:
    """摄取一个案例包（调用方负责事务与会话）。

    设计依据（公共案例库第 6 节、RAG 策略第 7 节）：

    - 只接导出物：ASR 与案例抽取都留在链外，我们只收 `manifest.json` +
      `L1_*.md` + `L2_*.json`。`_review.md` 只是人工阅读附件，不参与检索。
    - manifest 是必须补的一环：上游把元数据写在 L1 页脚里，机器不可读。
    - 缺失即拒绝导入：manifest 缺字段或卡片不通过值域校验时整包拒绝，
      不做部分导入——半个案例会以「已入库」的身份进入检索，而缺的那部分无人知晓。
    - 一份包一个事务：与资料摄取同一条纪律，不留「一半进去了」的状态。
    - 幂等：按 `source_path` + 包内容哈希判断，未变跳过。

    节点形状（第 1.3 节、第 2 节）：

    - 检索单位是卡片、呈现单位是案例——每张卡片整卡一个节点（不走进
      Markdown 分块链），卡片级命中在条目内聚合回案例；
    - `narrative` 的五节也作为可检索节点（按节切块）；
    - 卡片嵌入文本 = 全字段结构化拼接，`_inferred` 与标识字段不嵌入。

    Args:
        package_dir: 案例包目录（含 `manifest.json`）。

    Returns:
        `CaseIngestionResult`。

    Raises:
        CaseIngestionError: 包不合法、缺文件、嵌入失败或写库失败——调用方回滚整个事务。
        EmbeddingConfigurationError: 缺嵌入凭据（透传，调用方需区别于普通失败）。
    """
    manifest_path = package_dir / "manifest.json"
    try:
        manifest = load_manifest(manifest_path)
    except CasePackageError as exc:
        raise CaseIngestionError(str(exc)) from exc

    narrative_path = package_dir / manifest.narrative_file
    if not narrative_path.is_file():
        raise CaseIngestionError(f"manifest 引用的叙事文件不存在：{manifest.narrative_file}")

    cards, card_ids, card_paths = _load_cards(manifest, package_dir)

    try:
        raw_narrative = narrative_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CaseIngestionError(f"读取叙事文件失败：{type(exc).__name__}") from exc

    # 叙事文件若带 frontmatter，同样不参与分块（与资料侧同一理由：YAML 会污染检索）。
    _frontmatter, narrative_body = parse_frontmatter(raw_narrative)

    source_path = str(package_dir)
    doc_hash = _compute_package_hash(manifest_path, card_paths, narrative_path)

    existing = (await session.execute(select(CaseItem).where(CaseItem.source_path == source_path))).scalar_one_or_none()
    if existing is not None and existing.doc_hash == doc_hash:
        return CaseIngestionResult(
            source_path=source_path,
            item_id=str(existing.id),
            external_key=manifest.external_key,
            skipped=True,
        )

    narrative_chunks = split_narrative(narrative_body)
    if not narrative_chunks:
        raise CaseIngestionError("叙事文件未产生任何可检索小节（五节标题一个都没识别到）")

    manual = [c for c in narrative_chunks if c.needs_manual_review]
    embeddable_narrative = [c for c in narrative_chunks if not c.needs_manual_review]

    _assert_cards_within_limits(cards, card_ids)
    card_texts = [build_card_embedding_text(card) for card in cards]

    item = existing if existing is not None else CaseItem(source_path=source_path)
    item.external_key = manifest.external_key
    item.title = manifest.title
    item.source = manifest.authorization
    item.applicable_scope = _applicable_scope_from(manifest)
    item.authorization = manifest.authorization
    item.source_type = manifest.source_type
    item.evidence_level = manifest.evidence_level
    item.review_status = manifest.review_status
    item.interview_at = manifest.interview_at
    item.makes_claims_high_risk = any(_card_is_high_risk(card) for card in cards)
    item.inferred_fields = sorted({name for card in cards for name in inferred_field_names(card)})
    item.subject_type = manifest.subject_type
    item.consent_scope = manifest.consent_scope
    item.consent_recorded_at = manifest.consent_recorded_at
    item.reviewer = manifest.reviewer
    item.transcript_ref = manifest.transcript_ref
    item.keywords = manifest.keywords
    item.aliases = manifest.aliases
    item.status = manifest.status
    item.doc_hash = doc_hash
    if existing is None:
        session.add(item)
    await session.flush()  # 取到 item.id

    item_id = str(item.id)

    # 嵌入：卡片与叙事块一起批量送，减少往返（单请求建议 ≤128 条）。
    all_texts = [*card_texts, *(chunk.text for chunk in embeddable_narrative)]
    try:
        vectors = await embed_texts(settings, all_texts)
    except EmbeddingConfigurationError:
        raise
    except IngestionError as exc:
        raise CaseIngestionError(str(exc)) from exc

    card_vectors = vectors[: len(card_texts)]
    narrative_vectors = vectors[len(card_texts) :]

    # 先删该条目的旧节点再写新节点：更新与撤下走同一套机制，且与条目表同事务
    # （RAG 策略第 2 节：撤下要能同时改状态与删节点）。
    await session.execute(delete(RetrievedNode).where(RetrievedNode.node_id.like(f"{item_id}:%")))

    table = vector_store._table_class  # noqa: SLF001 —— 框架耦合点，由集成测试守护
    high_risk = item.makes_claims_high_risk
    for index, (card, card_id, text, vector) in enumerate(zip(cards, card_ids, card_texts, card_vectors, strict=True)):
        metadata = _card_metadata(manifest, item_id, card, card_id, locator=card["title"])
        # 案例级高风险一旦为真，逐卡也标为真：叙事与卡片的标记口径必须一致，
        # 否则同一案例的卡片说「低风险」而案例说「高风险」，skill 无从判断该信哪个。
        if high_risk:
            metadata["makes_claims_high_risk"] = "true"
        session.add(
            table(
                node_id=f"{item_id}:card:{index}",
                text=text,
                embedding=vector,
                metadata_=metadata,
            )
        )

    for chunk, vector in zip(embeddable_narrative, narrative_vectors, strict=True):
        session.add(
            table(
                node_id=f"{item_id}:narrative:{chunk.chunk_index}",
                text=chunk.text,
                embedding=vector,
                metadata_=_narrative_metadata(manifest, item_id, chunk, makes_claims_high_risk=high_risk),
            )
        )
    await session.flush()

    return CaseIngestionResult(
        source_path=source_path,
        item_id=item_id,
        external_key=manifest.external_key,
        cards_written=len(cards),
        narrative_nodes=len(embeddable_narrative),
        needs_manual_review=len(manual),
        locators=[card["title"] for card in cards] + [chunk.locator for chunk in embeddable_narrative],
    )


def _applicable_scope_from(manifest: CaseManifest) -> str:
    """案例的「适用范围」。

    案例包没有独立的 `applicable_scope` 字段（第 6 节的 manifest 形状里没有），
    而返回契约的 `applicable_scope` 是必带的（`RQ-CON-03`：输出要能说明适用条件
    与局限）。此处由被访谈对象类型 + 来源类型合成一个可读的适用范围，
    而不是编造一个不存在的字段：它如实说明「这是谁的、什么场景的经验」，
    正是使用者判断可迁移性所需的信息。

    取舍（如实记录）：这是从既有字段派生，不是上游给的原文；若上游将来补了
    `applicable_scope`，应以它为准并改这里（已登记在报告的未决问题节）。
    """
    return f"{manifest.subject_type}经验（{manifest.source_type}）"


async def ingest_case_package_file(
    settings: Settings,
    session: AsyncSession,
    *,
    vector_store: PGVectorStore,
    manifest_json: Path,
) -> CaseIngestionResult:
    """便捷入口：按 `manifest.json` 的路径推断包目录后摄取。

    Raises:
        CaseIngestionError: 目录不存在或包不合法。
    """
    package_dir = manifest_json.parent
    if not package_dir.is_dir():
        raise CaseIngestionError(f"案例包目录不存在：{package_dir}")
    return await ingest_case_package(settings, session, vector_store=vector_store, package_dir=package_dir)


__all__ = [
    "CARD_EVIDENCE_LEVELS",
    "HIGH_RISK_CARD_FIELDS",
    "NARRATIVE_SECTIONS",
    "CaseIngestionError",
    "CaseIngestionResult",
    "ingest_case_package",
    "ingest_case_package_file",
    "split_narrative",
]
