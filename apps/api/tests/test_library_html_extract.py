"""HTML → Markdown 加工的单元测试（不连库、不调模型）。

覆盖 RAG 策略第 1.1 节对语料加工的要求：标题层级保留（分块链的硬依赖）、
表格转 Markdown、正文容器优先级、噪声与元信息剔除、**丢弃内容必须留痕**、
frontmatter 从出版方元数据生成。

反空壳取向：每个用例都断言**具体内容**（层级、单元格文字、留痕文案），
而不是只断言"没抛异常"——后者是永远不会失败的检查。
"""

from __future__ import annotations

from campfire.modules.library.html_extract import (
    _IMAGE_MARKER,
    build_markdown,
    convert_html,
)


def _page(body: str, *, head: str = "", article_class: str = "") -> str:
    """包一个最小网页骨架。"""
    cls = f' class="{article_class}"' if article_class else ""
    return f"<html><head>{head}</head><body><article{cls}>{body}</article></body></html>"


# ---------------------------------------------------------------- 标题层级


def test_heading_levels_map_to_atx() -> None:
    """h1–h6 映射为 `#`–`######`——分块链靠它写 header_path。"""
    body = "<h1>一级</h1><h2>二级</h2><h3>三级</h3><h4>四级</h4><h5>五级</h5><h6>六级</h6>"

    result = convert_html(_page(body))

    assert "## 二级" in result.markdown
    assert "### 三级" in result.markdown
    assert "###### 六级" in result.markdown


def test_headings_beyond_six_are_clamped() -> None:
    """Markdown 只到六级；超出不产生非法标题。"""
    result = convert_html(_page("<h6>六级</h6>"))

    assert "####### " not in result.markdown
    assert "###### 六级" in result.markdown


def test_empty_heading_is_skipped() -> None:
    """空标题不产生空 `#` 行（那会切出一个无名 section）。"""
    result = convert_html(_page("<h2></h2><p>正文</p>"))

    assert "#" not in result.markdown
    assert "正文" in result.markdown


# ---------------------------------------------------------------- 正文容器


def test_body_main_article_body_wins_over_larger_article() -> None:
    """更精确的语义容器优先于更大的 `<article>`。

    实测依据（PMC）：`<article>` 87,195 字符 > `main-article-body` 80,523——
    多出的是 front-matter 的作者与单位。若按"文本最多"选，作者名会变成 `###`
    标题并错误嵌套后续正文。
    """
    html = """
    <html><body><article>
      <section class="front-matter"><h3>作者甲</h3><p>某单位</p></section>
      <section class="body main-article-body"><h2>正文</h2><p>这是正文。</p></section>
    </article></body></html>
    """

    result = convert_html(html)

    assert result.container == "section.body.main-article-body"
    assert "作者甲" not in result.markdown, "元信息容器必须被剔除"


def test_falls_back_to_body_and_reports_it() -> None:
    """没有正文容器时退回 `body`，并**如实报告**用了兜底（不假装选到正文）。"""
    html = "<html><body><div><p>裸正文</p></div></body></html>"

    result = convert_html(html)

    assert result.container == "body"
    assert "裸正文" in result.markdown


def test_missing_body_raises() -> None:
    """既无容器也无 body 时明确失败，而不是产出空产物假装成功。"""
    import pytest

    with pytest.raises(ValueError, match="正文"):
        convert_html("<html><head></head></html>")


def test_front_matter_section_is_dropped() -> None:
    """`front-matter` / `author-notes` 等元信息容器整体剔除。"""
    body = (
        '<section class="front-matter"><h3>作者甲</h3><p>单位</p></section>'
        '<section class="author-notes"><p>通讯作者</p></section>'
        "<h2>正文标题</h2><p>正文内容。</p>"
    )

    result = convert_html(_page(body))

    assert "作者甲" not in result.markdown
    assert "通讯作者" not in result.markdown
    assert "正文内容" in result.markdown


# ---------------------------------------------------------------- 表格


def test_table_becomes_markdown_table() -> None:
    """表格转成 Markdown 表格，单元格文字保留。"""
    body = "<table><tr><th>实践</th><th>证据</th></tr><tr><td>视觉支持</td><td>强</td></tr></table>"

    result = convert_html(_page(body))

    assert "| 实践 | 证据 |" in result.markdown
    assert "|---|---|" in result.markdown
    assert "| 视觉支持 | 强 |" in result.markdown


def test_ragged_table_rows_are_padded_and_disclosed() -> None:
    """单元格数不一致的行按列数补齐，并**留痕**（Markdown 表格要求矩形）。"""
    body = "<table><tr><th>甲</th><th>乙</th></tr><tr><td>只有一个</td></tr></table>"

    result = convert_html(_page(body))

    assert "| 只有一个 |  |" in result.markdown
    assert "不一致" in result.markdown, "补齐是有损的，必须留痕"


def test_table_without_rows_is_dropped_silently_only_because_empty() -> None:
    """空表格不产出空表格语法（无内容可丢，不算静默丢弃）。"""
    result = convert_html(_page("<table></table><p>正文</p>"))

    assert "|---|" not in result.markdown
    assert "正文" in result.markdown


# ---------------------------------------------------------------- 列表


def test_unordered_list_becomes_dash_items() -> None:
    """`<ul>` 转成 `-` 列表。"""
    result = convert_html(_page("<ul><li>甲</li><li>乙</li></ul>"))

    assert "- 甲" in result.markdown
    assert "- 乙" in result.markdown


def test_ordered_list_becomes_numbered_items() -> None:
    """`<ol>` 转成编号列表。"""
    result = convert_html(_page("<ol><li>第一步</li><li>第二步</li></ol>"))

    assert "1. 第一步" in result.markdown
    assert "2. 第二步" in result.markdown


def test_nested_list_is_indented() -> None:
    """嵌套列表缩进保留层级。"""
    body = "<ul><li>外层<ul><li>内层</li></ul></li></ul>"

    result = convert_html(_page(body))

    assert "- 外层" in result.markdown
    assert "  - 内层" in result.markdown


# ---------------------------------------------------------------- 去噪与留痕


def test_noise_tags_are_dropped_and_counted() -> None:
    """`script`/`nav`/`footer` 等剔除并计数。"""
    body = "<nav>导航</nav><script>var x=1;</script><footer>页脚</footer><p>真正的正文</p>"

    result = convert_html(_page(body))

    assert "导航" not in result.markdown
    assert "var x" not in result.markdown
    assert "页脚" not in result.markdown
    assert "真正的正文" in result.markdown
    assert result.noise_dropped >= 3


def test_image_is_replaced_by_a_visible_marker() -> None:
    """图片不接线（一期不支持），但**必须留痕**——不静默丢弃。"""
    result = convert_html(_page('<p>前</p><img src="a.png" alt="图"/><p>后</p>'))

    assert result.images_dropped == 1
    assert _IMAGE_MARKER in result.markdown
    assert "前" in result.markdown and "后" in result.markdown


def test_inline_formatting_is_preserved() -> None:
    """粗体、斜体、行内代码保留 Markdown 语义。"""
    body = "<p>这是<strong>重点</strong>与<em>强调</em>以及<code>代码</code>。</p>"

    result = convert_html(_page(body))

    assert "**重点**" in result.markdown
    assert "*强调*" in result.markdown
    assert "`代码`" in result.markdown


def test_code_block_is_fenced() -> None:
    """`<pre>` 转成围栏代码块。"""
    result = convert_html(_page("<pre>line1\nline2</pre>"))

    assert "```" in result.markdown
    assert "line1" in result.markdown


def test_block_level_link_keeps_its_text() -> None:
    """块级链接的文本是正文内容，**必须保留**。

    已修缺陷的回归（2026-09-29）：早先 `<a>` 一律直接 return，导致 PMC 页面里
    「Supplementary file1 (PDF 160 KB)」这类补充材料链接整条消失——守恒对账
    抓到了它（364 个正文文本节点中有 1 个缺失）。
    """
    body = '<div class="caption"><a href="/x.pdf">Supplementary file1 (PDF 160 KB)</a></div>'

    result = convert_html(_page(body))

    assert "Supplementary file1 (PDF 160 KB)" in result.markdown
    assert result.links_seen == 1


def test_figure_control_link_is_dropped() -> None:
    """`<figure>` 内的交互控件不是内容（如「Open in a new tab」），丢弃。"""
    body = '<figure><img src="a.png"/><div><a href="#">Open in a new tab</a></div></figure>'

    result = convert_html(_page(body))

    assert "Open in a new tab" not in result.markdown
    assert _IMAGE_MARKER in result.markdown, "图本身仍须留痕"


def test_blank_target_control_link_is_dropped_outside_figure() -> None:
    """控件判据不能只看 `<figure>`：实测同一页面的控件有的在 figure 内、
    有的在普通 `section` 里（PMC 的 `section.tw`）。

    通用特征是 `target="_blank"` + `rel="noopener"`（打开界面面板而非内容），
    这是网页约定而非站点特定 class——按 class 判会随站点改版失效。
    """
    body = (
        '<section class="tw"><div class="p text-right">'
        '<a href="figure/Fig1/" target="_blank" rel="noopener noreferrer">Open in a new tab</a>'
        "</div></section>"
    )

    result = convert_html(_page(body))

    assert "Open in a new tab" not in result.markdown


def test_link_in_figure_without_blank_target_is_still_dropped() -> None:
    """`<figure>` 内的链接即便没有 `target` 也按控件处理（保守）。"""
    body = '<figure><a href="fig.png">放大查看</a></figure>'

    result = convert_html(_page(body))

    assert "放大查看" not in result.markdown


def test_inline_link_text_is_kept_without_url() -> None:
    """行内链接保留可见文字（一期不保留 URL，正文可读优先）。"""
    body = '<p>详见<a href="https://example.org">国家卫健委指南</a>。</p>'

    result = convert_html(_page(body))

    assert "国家卫健委指南" in result.markdown


# ---------------------------------------------------------------- 元数据


def test_citation_metadata_is_extracted() -> None:
    """从 `citation_*` / `DC.*` 抽元数据——用出版方标注而非人工转写。"""
    head = (
        '<meta name="citation_title" content="循证实践综述"/>'
        '<meta name="citation_doi" content="10.1007/s10803-020-04844-2"/>'
        '<meta name="citation_journal_title" content="JADD"/>'
        '<meta name="citation_publication_date" content="2021 Jan 15"/>'
        '<meta name="citation_author" content="Kara Hume"/>'
        '<meta name="citation_author" content="Samuel L Odom"/>'
        '<meta name="citation_fulltext_html_url" content="https://example.org/a"/>'
    )

    result = convert_html(_page("<h2>正文</h2>", head=head))

    assert result.metadata["title"] == "循证实践综述"
    assert result.metadata["doi"] == "10.1007/s10803-020-04844-2"
    assert result.metadata["journal"] == "JADD"
    assert result.metadata["published_at"] == "2021 Jan 15"
    assert result.metadata["authors"] == "Kara Hume; Samuel L Odom"
    assert result.metadata["source_url"] == "https://example.org/a"


def test_metadata_defaults_to_dc_and_og() -> None:
    """`citation_*` 缺失时回落到 `DC.*` / `og:*`。"""
    head = '<meta name="DC.Title" content="题名"/><meta property="og:url" content="https://x.org"/>'

    result = convert_html(_page("<p>正文</p>", head=head))

    assert result.metadata["title"] == "题名"
    assert result.metadata["source_url"] == "https://x.org"


def test_license_statement_is_carried_through() -> None:
    """许可声明原样带出，供 `EVID-B` 闸门人工判定（不代替判定）。"""
    head = '<meta name="DC.Rights" content="CC BY-NC 4.0, no commercial re-use"/>'

    result = convert_html(_page("<p>正文</p>", head=head))

    assert "CC BY-NC" in result.metadata["license_statement"]


# ---------------------------------------------------------------- frontmatter


def test_build_markdown_emits_frontmatter_and_root_heading() -> None:
    """frontmatter 与根标题齐备——摄取链要求前者，分块链要求后者。"""
    conversion = convert_html(_page("<h2>摘要</h2><p>正文。</p>"))

    text = build_markdown(
        conversion,
        title="测试标题",
        source="某机构 2024",
        applicable_scope="学龄前儿童",
        license_note="CC BY 4.0",
    )

    assert text.startswith("---\n")
    assert "title: 测试标题" in text
    assert "source: 某机构 2024" in text
    assert "applicable_scope: 学龄前儿童" in text
    assert "license: CC BY 4.0" in text
    assert "\n# 测试标题\n" in text


def test_build_markdown_uses_metadata_title_when_flag_absent() -> None:
    """未传 `--title` 时用元数据标题补根标题。

    这是一个已修缺陷的回归：只按显式参数判断会漏掉元数据来源的标题，
    产出的正文没有一级标题，所有 `##` 都挂在根上、层级信息不完整。
    """
    head = '<meta name="citation_title" content="来自元数据的题名"/>'
    conversion = convert_html(_page("<h2>摘要</h2>", head=head))

    text = build_markdown(conversion)

    assert "\n# 来自元数据的题名\n" in text


def test_build_markdown_does_not_duplicate_existing_h1() -> None:
    """正文已有一级标题时不重复补。"""
    conversion = convert_html(_page("<h1>原有标题</h1><p>正文</p>"))

    text = build_markdown(conversion, title="传入的标题")

    assert text.count("\n# ") == 1
    assert "原有标题" in text


def test_yaml_values_round_trip_through_the_reader() -> None:
    """frontmatter 值的写入必须能被读回——用**往返**断言而不是文本匹配。

    这是已修缺陷的回归（2026-09-29 实测）：写侧把 `"` 转义成 `\\"`，读侧只
    `strip('"')`，读回的值就多一个反斜杠——**语料里的标题被静默改写**。
    用文本匹配写死格式抓不到这类问题（我第一版断言正是错在这里：全角冒号
    在 YAML 里其实不需要引号）。
    """
    from campfire.modules.library.ingestion import parse_frontmatter

    cases = [
        "带 # 井号的标题",  # 不加引号会被当注释截断
        "source: 含半角冒号",  # 不加引号会报 ScannerError
        '含引号" 的标题',  # 转义必须与读侧对称
        "标题：含全角冒号",  # 全角冒号无需引号，但值必须保真
        "多行\n标题",  # 换行须压平，否则破坏一key一行的结构
    ]
    conversion = convert_html(_page("<p>正文</p>"))

    for value in cases:
        text = build_markdown(conversion, title=value)
        metadata, body = parse_frontmatter(text)

        expected = value.replace("\n", " ").strip()
        assert metadata.get("title") == expected, f"{value!r} 往返失真"
        assert "\n# " in text, "根标题仍须存在"


def test_derivation_records_what_was_dropped() -> None:
    """`derivation` 记录加工方式与丢弃内容——加工的痕迹随语料存活。"""
    conversion = convert_html(_page('<nav>导航</nav><img src="a.png"/><p>正文</p>'))

    text = build_markdown(conversion, title="标题")

    assert "derivation:" in text
    assert "图片" in text
    assert "噪声" in text
