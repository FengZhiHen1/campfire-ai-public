"""HTML → Markdown 加工：把网页原件整理成可摄取的语料件（RAG 策略第 1.1 节）。

职责：把网页原件转成带 frontmatter 的 Markdown 语料件（正文、出处、丢弃记账）。
边界：只做机械转换，不判断许可、不判断内容是否为所需；不读文件、不写文件、不连库、不调模型（文件入口除外）。
参考：docs/技术设计/technical-details/RAG策略.md 第 1.1 节；docs/技术设计/decisions/检索链归入library模块.md；细节见 `convert_html`、`_render_block`、`_extract_metadata` 的 docstring。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Tag

#: 正文容器候选，按优先级排列。实测依据（2026-09-29）：
#: - 学术出版页常把正文单独放进语义容器（PMC 用 `section.body.main-article-body`，
#:   实测 80,523 字符 vs `<article>` 的 87,195——后者含 front-matter 的作者与单位，
#:   那些会被渲染成 `###` 标题、把后续正文错误嵌套）；
#: - 一般页面用 `<article>` 可覆盖全文文本的 83–86%，是有效边界；
#: - 都找不到时退回 `body`，并在报告里标注（不假装选到了正文）。
_CONTENT_SELECTORS = (
    "section.body.main-article-body",
    "div.main-article-body",
    "article .body",
    "article",
    "main",
    '[role="main"]',
)

#: 元信息容器：作者、单位、投稿历史、版权声明。它们在页面里常被标成 `h3`，
#: 若留在正文会与真正的章节标题混进同一棵 `header_path` 树，让分块归属出错。
#: 实测（PMC）：`section.front-matter` 装 4,916 字符的作者与单位信息。
_FRONT_MATTER_CLASSES = ("front-matter", "author-notes", "history", "article-notes", "ameta")

#: 整块丢弃的元素：与正文无关，或内容不可检索。
_DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "aside",
    "form",
    "button",
    "iframe",
    "svg",
    "template",
)

#: 噪声容器（按 class/id 命中即整块丢弃）。网页框架常把导航也放进 <article>。
_NOISE_CLASS_PATTERN = re.compile(
    r"(?:^|[-_ ])(?:nav|navigation|menu|sidebar|breadcrumb|footer|header|"
    r"cookie|banner|advert|ad-|social|share|related|recommend|popup|modal|"
    r"skip|toolbar|search)(?:$|[-_ ])",
    re.IGNORECASE,
)

#: 标题层级上限：Markdown 只到 6 级。
_MAX_HEADING_LEVEL = 6

#: 图片引用（Markdown 语法），用于识别并留痕。
_IMAGE_MARKER = "（此处原件有图片，一期不支持图片，未接入）"


@dataclass
class HtmlConversion:
    """一次 HTML 转换的产物与如实记账。"""

    #: 转换出的 Markdown 正文（不含 frontmatter，由调用方拼接）。
    markdown: str
    #: 选中的正文容器选择器；退回 `body` 时是 `"body"`。
    container: str
    #: 从出版方元数据抽出的 frontmatter 键值（可能为空）。
    metadata: dict[str, str] = field(default_factory=dict)
    #: 丢弃的图片数（已就地留痕，不静默丢）。
    images_dropped: int = 0
    #: 丢弃的噪声块数（导航、页脚等）。
    noise_dropped: int = 0
    #: 是否在正文里发现了链接（一期不保留链接目标的脚注，仅作记账）。
    links_seen: int = 0


def _pick_container(soup: BeautifulSoup) -> tuple[Tag, str]:
    """选正文容器：按候选优先级取第一个命中的选择器，取其文本最多的匹配。

    为什么按优先级而不是全局取最大（2026-09-29 实测教训）：学术出版页的
    `<article>` 比正文容器更大（含 front-matter 的作者与单位，实测 87,195
    vs 80,523 字符）。若一律取"文本最多"，更精确的语义容器永远赢不了，
    作者名会被渲染成 `###` 标题并错误嵌套后续正文。

    优先级耗尽后退回 `body` 并在返回值中标注——不假装选到了正文。
    """
    for selector in _CONTENT_SELECTORS:
        candidates = soup.select(selector)
        if not candidates:
            continue
        # 同一选择器内取文本最多的一个（可能命中多个摘要卡片）。
        best = max(candidates, key=lambda c: len(c.get_text(strip=True)))
        return best, selector

    body = soup.body
    if body is None:
        raise ValueError("HTML 中既无正文容器也没有 <body>，无法确定正文范围")
    return body, "body"


def _is_noise(tag: Tag) -> bool:
    """判断是否是导航/页脚/元信息一类噪声容器。"""
    if tag.name in _DROP_TAGS:
        return True
    for attr in ("class", "id", "role"):
        value = tag.get(attr)
        if value is None:
            continue
        text = " ".join(value) if isinstance(value, list) else str(value)
        if _NOISE_CLASS_PATTERN.search(text):
            return True
        if _has_front_matter_class(value):
            return True
    return False


def _has_front_matter_class(value: object) -> bool:
    """判断 class/id 是否命中元信息容器清单（作者、单位、投稿历史、版权）。"""
    tokens = value if isinstance(value, list) else [str(value)]
    return any(token in _FRONT_MATTER_CLASSES for token in tokens)


def _clean_text(text: str) -> str:
    """归一空白：HTML 里的换行与缩进不代表语义，压成单空格。"""
    return re.sub(r"\s+", " ", text).strip()


def _inline_text(tag: Tag) -> str:
    """取行内文本，保留代码与强调的 Markdown 语义。"""
    pieces: list[str] = []
    for child in tag.children:
        if isinstance(child, Tag):
            if child.name in {"script", "style", "noscript"}:
                continue
            if child.name == "code":
                pieces.append(f"`{_clean_text(child.get_text())}`")
            elif child.name in {"strong", "b"}:
                inner = _clean_text(child.get_text())
                pieces.append(f"**{inner}**" if inner else "")
            elif child.name in {"em", "i"}:
                inner = _clean_text(child.get_text())
                pieces.append(f"*{inner}*" if inner else "")
            elif child.name == "br":
                pieces.append(" ")
            elif child.name == "a":
                pieces.append(_inline_text(child))
            else:
                pieces.append(_inline_text(child))
        else:
            pieces.append(_clean_text(str(child)))
    # 压掉重复空格（逐元素拼接会留下多处空白）。
    return re.sub(r"\s+", " ", "".join(pieces)).strip()


def _table_to_markdown(table: Tag, report: HtmlConversion) -> str:
    """把 `<table>` 转成 Markdown 表格。

    行内单元格数不一致时以首行为列数补齐/截断——Markdown 表格要求矩形；
    这是有损的，因此把不一致的行数记账到报告（不静默）。
    """
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        rows.append([_inline_text(cell) for cell in cells])

    if not rows:
        return ""

    width = max(len(r) for r in rows)
    normalized: list[list[str]] = []
    ragged = 0
    for row in rows:
        if len(row) != width:
            ragged += 1
            row = row + [""] * (width - len(row))
        normalized.append(row[:width])

    header = normalized[0]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")

    if ragged:
        report.noise_dropped += 0  # 保持字段语义清晰：不计入噪声
        lines.append("")
        lines.append(f"（原件此表有 {ragged} 行单元格数与其他行不一致，已按列数补齐）")
    return "\n".join(lines)


def _render_list(list_tag: Tag, report: HtmlConversion, depth: int = 0) -> str:
    """把 `<ul>`/`<ol>` 转成 Markdown 列表（含嵌套）。"""
    ordered = list_tag.name == "ol"
    lines: list[str] = []
    index = 0
    for li in list_tag.find_all("li", recursive=False):
        index += 1
        marker = f"{index}." if ordered else "-"
        # 列表项内部的段落取文本，嵌套列表递归。
        nested = [c for c in li.find_all(["ul", "ol"], recursive=False)]
        for n in nested:
            n.extract()

        text = _inline_text(li)
        if text:
            lines.append(f"{'  ' * depth}{marker} {text}")
        for n in nested:
            rendered = _render_list(n, report, depth + 1)
            if rendered:
                lines.append(rendered)
    return "\n".join(lines)


def _render_block(tag: Tag, report: HtmlConversion, out: list[str]) -> None:
    """按块级元素递归渲染。

    为什么自己写序列化而不找现成转换库（2026-09-29 定）：

    - 需要完全控制标题层级（`h1–h6` → `#–######`）——它是分块链的硬依赖，
      转换库的层级约定不一定等于 Markdown 的 ATX 标题；
    - 需要表格转 Markdown 表格且与 `chunking.py` 的表格行识别（`|...|`）
      保持一致；
    - 需要对丢弃的内容留痕（图片、未选中的容器）——通用转换库静默丢内容，
      而"不静默丢弃"是本项目的铁律；
    - 需要从出版方元数据生成 frontmatter（`citation_*`/`DC.*`），把出处、
      DOI、许可随语料一起带走（`EVID-B` 的判据）。
    """
    if _is_noise(tag):
        report.noise_dropped += 1
        return

    name = tag.name

    if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = min(int(name[1]), _MAX_HEADING_LEVEL)
        text = _inline_text(tag)
        if text:
            out.append(f"{'#' * level} {text}")
        return

    if name == "p":
        text = _inline_text(tag)
        if text:
            out.append(text)
        return

    if name == "table":
        rendered = _table_to_markdown(tag, report)
        if rendered:
            out.append(rendered)
        return

    if name in {"ul", "ol"}:
        rendered = _render_list(tag, report)
        if rendered:
            out.append(rendered)
        return

    if name == "blockquote":
        inner: list[str] = []
        for child in tag.children:
            if isinstance(child, Tag):
                _render_block(child, report, inner)
        for line in "\n".join(inner).splitlines():
            out.append(f"> {line}" if line else ">")
        return

    if name == "pre":
        code = tag.get_text()
        if code.strip():
            out.append(f"```\n{code.rstrip()}\n```")
        return

    if name == "img":
        report.images_dropped += 1
        out.append(_IMAGE_MARKER)
        return

    if name == "a":
        # 块级链接：文本是正文内容的一部分，必须保留。
        # 实测教训（2026-09-29）：早先这里直接 return，导致 PMC 页面里
        # 「Supplementary file1 (PDF 160 KB)」这类补充材料链接整条消失——
        # 是真实内容丢失，不是噪声（守恒对账抓到了它）。
        #
        # 例外：界面控件。实测该类链接的结构特征是带 `target="_blank"` 与
        # `rel="noopener"`（如「Open in a new tab」，它打开的是图片查看面板，
        # href 指向 `figure/Fig1/` 而非内容）。这是通用网页约定，不是站点特定
        # class 名——按 class 判会随站点改版失效。父级是 `figure` 同样视为控件。
        is_control = tag.get("target") == "_blank" or any(ancestor.name == "figure" for ancestor in tag.parents)
        if is_control:
            return
        text = _inline_text(tag)
        if text:
            out.append(text)
        report.links_seen += 1
        return

    if name in {"figure", "figcaption"}:
        # 图与图注：图片本身留痕，图注文本保留（常含关键信息）。
        # 递归而不是整体取文本：整体取文本会把 figure 内的交互控件
        # （如「Open in a new tab」）也带进来，而控件应由 `<a>` 分支按结构丢弃。
        inner: list[str] = []
        for child in tag.children:
            if isinstance(child, Tag):
                _render_block(child, report, inner)
            else:
                text = _clean_text(str(child))
                if text:
                    inner.append(text)
        if tag.name == "figure" and tag.find("img") is not None:
            report.images_dropped += 1
            inner.append(_IMAGE_MARKER)
        out.extend(block for block in inner if block.strip())
        return

    if name in {"div", "section", "article", "main", "span", "li", "td", "th", "dl", "dd", "dt"}:
        for child in tag.children:
            if isinstance(child, Tag):
                _render_block(child, report, out)
            else:
                text = _clean_text(str(child))
                if text:
                    out.append(text)
        return

    # 未知块级元素：递归下去，不吞内容。
    for child in tag.children:
        if isinstance(child, Tag):
            _render_block(child, report, out)


def _extract_metadata(soup: BeautifulSoup) -> dict[str, str]:
    """从出版方元数据标签抽 frontmatter 字段。

    用出版方自己的元数据而非人工转写：出处、DOI、日期由发布方标注，
    转写会引入错误。同时它是内容身份校验的材料——采集过程出现过
    "编号猜错、抓回完全无关文献且 HTTP 200"的实例。

    许可与内容身份：本模块只做机械转换，不判断许可、不判断内容是否为所需。
    从 `citation_*` meta 抽出的 DOI/标题写入 frontmatter 供人工核对——采集清单里
    有过"凭猜测的 PMC 编号抓回完全无关文献且 HTTP 200"的实例，身份校验不能只看
    "文件在不在"。
    """

    def meta(*names: str) -> str:
        for name in names:
            for key in ("name", "property"):
                tag = soup.find("meta", attrs={key: name})
                if tag is not None:
                    content = tag.get("content")
                    if content:
                        return _clean_text(str(content))
        return ""

    metadata: dict[str, str] = {}

    title = meta("citation_title", "DC.Title", "og:title")
    if title:
        metadata["title"] = title

    doi = meta("citation_doi", "DC.Identifier")
    if doi:
        metadata["doi"] = doi

    journal = meta("citation_journal_title")
    if journal:
        metadata["journal"] = journal

    date = meta("citation_publication_date", "DC.Date")
    if date:
        metadata["published_at"] = date

    authors = [
        _clean_text(str(tag.get("content")))
        for tag in soup.find_all("meta", attrs={"name": "citation_author"})
        if tag.get("content")
    ]
    if authors:
        metadata["authors"] = "; ".join(authors)

    url = meta("citation_public_url", "citation_fulltext_html_url", "og:url")
    if url:
        metadata["source_url"] = url

    # 许可：站点常用 DC.Rights / citation_* 标注，
    # 原样带出供人工判定。
    rights = meta("DC.Rights", "DC.Rights.Copyright", "citation_license")
    if rights:
        metadata["license_statement"] = rights

    return metadata


def convert_html(html: str) -> HtmlConversion:
    """把 HTML 转成 Markdown 正文与元数据。

    为什么需要这一层：设计规定"系统不解析 PDF"、「HTML 同样在链外清理」——
    语料必须已处理好的 Markdown 或 HTML 才进系统，而"分块依赖标题层级"
    （`MarkdownNodeParser` 靠 `#` 写 `header_path`）。原始网页是导航、页脚、脚本
    与正文混杂的树，直接入库会让噪声进入检索、并让正文失去层级。

    BeautifulSoup 只承担"解析成树"这一纯通用件，遍历与序列化由本模块持有。

    纯度：不读文件、不写文件、不连库、不调模型——便于测试与复用，
    也保证"转换"这一步零成本、可先审后喂。

    Raises:
        ValueError: HTML 里既无正文容器也没有 `<body>` 时。
    """
    soup = BeautifulSoup(html, "lxml")
    report = HtmlConversion(markdown="", container="")

    container, selector = _pick_container(soup)
    report.container = selector
    report.metadata = _extract_metadata(soup)

    blocks: list[str] = []
    for child in container.children:
        if isinstance(child, Tag):
            _render_block(child, report, blocks)
        else:
            text = _clean_text(str(child))
            if text:
                blocks.append(text)

    # 去掉空块、压掉连续空行。
    cleaned = [b.strip() for b in blocks if b and b.strip()]
    report.markdown = re.sub(r"\n{3,}", "\n\n", "\n\n".join(cleaned)).strip()
    return report


def _yaml_value(value: str) -> str:
    """frontmatter 值的安全写法。

    三条规则都来自实测（2026-09-29 用 PyYAML 验证）：

    - 含 `#` 必须加引号：不加会被当成注释，实测 `"带 # 井号"` 读回只有 `"带"`
      ——静默截断，比报错更危险；
    - 含半角 `:` 必须加引号：会让解析器认为是嵌套映射（`ScannerError`）；
    - 换行必须压成空格：frontmatter 是「一key一行」的格式（读侧按行切），
      带换行的值会破坏结构。标题与出处里的换行本就是排版换行，压成空格无损。

    全角冒号 `：` 在 YAML 里是普通字符，不需要引号（实测确认）。
    """
    normalized = re.sub(r"\s*\n\s*", " ", value).strip()
    if any(ch in normalized for ch in (":", "#", '"', "'")) or normalized != value:
        escaped = normalized.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return normalized


def build_markdown(
    conversion: HtmlConversion,
    *,
    title: str | None = None,
    source: str | None = None,
    applicable_scope: str | None = None,
    license_note: str | None = None,
) -> str:
    """把转换结果拼成带 frontmatter 的语料件。

    frontmatter 的键与摄取链的约定一致（`source`/`applicable_scope`/`title` 等，
    见 ingestion.parse_frontmatter）；`derivation` 记录加工方式与丢弃的内容，
    让"做了什么加工"随语料存活——不静默丢弃。
    """
    meta = dict(conversion.metadata)
    if title:
        meta["title"] = title
    if source:
        meta["source"] = source
    if applicable_scope:
        meta["applicable_scope"] = applicable_scope
    if license_note:
        meta["license"] = license_note

    # 最终生效的标题：命令行优先，否则用页面元数据的。
    effective_title = title or meta.get("title", "")

    dropped: list[str] = []
    if conversion.images_dropped:
        dropped.append(f"图片 {conversion.images_dropped} 张（一期不支持图片，已在原位留痕）")
    if conversion.noise_dropped:
        dropped.append(f"导航/页脚/元信息一类噪声块 {conversion.noise_dropped} 个")
    meta["derivation"] = (
        f"由 {conversion.container} 容器抽取正文并转为 Markdown；"
        + ("丢弃：" + "、".join(dropped) + "；" if dropped else "")
        + "标题层级按 h1–h6 映射"
    )

    lines = ["---"]
    for key, value in meta.items():
        lines.append(f"{key}: {_yaml_value(str(value))}")
    lines.append("---")
    lines.append("")

    body = conversion.markdown
    # 正文若没有一级标题，用生效标题补一个——分块链依赖 `#` 层级给出根
    # `header_path`；缺了它所有 `##` 都挂在根上，层级信息不完整。
    if effective_title and not body.lstrip().startswith("# "):
        body = f"# {effective_title}\n\n{body}"

    return "\n".join(lines) + "\n" + body + "\n"


def convert_html_file(
    path: Path,
    *,
    title: str | None = None,
    source: str | None = None,
    applicable_scope: str | None = None,
    license_note: str | None = None,
) -> tuple[str, HtmlConversion]:
    """读一个 HTML 文件并转成语料件文本。

    归属：数据加工属检索链的一部分，因此归 `modules/library`（与摄取链同模块，
    依据见 decisions/检索链归入library模块.md）。CLI 只负责命令行形态。

    标题优先级与摄取链同一条（`ingestion.ingest_file`：`title or
    frontmatter.get("title") or path.stem`）：显式传入的 `title` 压过页面元数据，
    不传则用元数据——命令行覆盖必须真的有覆盖效果。

    Raises:
        OSError: 读取失败。
        ValueError: 正文范围无法确定。
    """
    html = path.read_text(encoding="utf-8", errors="replace")
    conversion = convert_html(html)
    markdown = build_markdown(
        conversion,
        title=title,
        source=source,
        applicable_scope=applicable_scope,
        license_note=license_note,
    )
    return markdown, conversion
