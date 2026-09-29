"""``python -m campfire.cli`` 的入口。

设计（RAG 策略第 7 节）把摄取定成**应用包内的一个 CLI 入口**，跑在同一镜像里、
连同一个库；**不暴露成服务端点**。提取逻辑归 ``modules/library``（检索链与摄取
同属一个模块），本入口只负责命令行形态、参数解析与退出码。

用法::

    python -m campfire.cli convert <input.html> [--out <output.md>]
    python -m campfire.cli ingest  <路径> --source <出处> --scope <适用范围>

**为什么 convert 与 ingest 分成两条命令**（2026-09-29 定）：设计要求语料"加工后
**＋人工核对标题与表格**"才进系统（RAG 策略第 1.1 节）。convert 是**纯转换**——
不连库、不调模型、零成本，产物可先审再喂；把转换并进 ingest 会跳过"审"这一步，
而那正是链外准备买到的东西。

退出码：0 成功、1 失败（含参数错误）、2 未实现的子命令。失败时说明原因，
不静默成功——摄取失败的可见性是设计要求的（「不留下『一半进去了』的静默状态」）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from campfire.core.config import get_settings
from campfire.core.db import create_engine, session_scope
from campfire.modules.library.embedding import EmbeddingConfigurationError
from campfire.modules.library.html_extract import convert_html_file
from campfire.modules.library.ingestion import (
    IngestionError,
    build_vector_store,
    ingest_file,
)

_USAGE = """campfire.cli —— 本地运维入口（不暴露成服务端点）

子命令：
  convert <input.html>   把网页原件转成可摄取的 Markdown（不连库、可先审后喂）
  ingest  <路径>         摄取处理好的 Markdown 文件到资料库

示例：
  python -m campfire.cli convert corpus/guide.html --out corpus/guide.md
  python -m campfire.cli ingest corpus/guide.md --source "WHO 2024" --scope "学龄前儿童"
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m campfire.cli", description="篝火智答本地运维入口")
    sub = parser.add_subparsers(dest="command")

    convert = sub.add_parser("convert", help="把 HTML 转成可摄取的 Markdown（不连库）")
    convert.add_argument("path", type=Path, help="待转换的 HTML 文件")
    convert.add_argument("--out", type=Path, default=None, help="输出路径；缺省写到输入文件同目录同名 .md")
    convert.add_argument("--source", default=None, help="出处；缺省用页面元数据，仍缺则留空待人工补")
    convert.add_argument("--scope", default=None, help="适用人群与情境；缺省留空待人工补")
    convert.add_argument("--license", dest="license_note", default=None, help="许可结论；缺省带出页面声明")
    convert.add_argument("--title", default=None, help="标题；缺省用页面元数据")

    ingest = sub.add_parser("ingest", help="摄取 Markdown 文件到资料库")
    ingest.add_argument("path", type=Path, help="待摄取的 Markdown 文件")
    ingest.add_argument(
        "--source",
        default=None,
        help="出处：机构、年份、链接或文件引用。可省略——文件 frontmatter 的 source 同样有效；两者都缺则拒绝入库",
    )
    ingest.add_argument(
        "--scope",
        default=None,
        help="适用人群与情境。可省略——文件 frontmatter 的 applicable_scope 同样有效；两者都缺则拒绝入库",
    )
    ingest.add_argument("--title", default=None, help="标题；缺省用 frontmatter 的 title，再缺省用文件名")
    ingest.add_argument("--keywords", default="", help="字面路关键词，空格分隔（覆盖 frontmatter）")
    ingest.add_argument("--aliases", default="", help="字面路别名，空格分隔（覆盖 frontmatter）")
    return parser


def _run_convert(args: argparse.Namespace) -> int:
    """执行转换：纯函数式加工，不连库、不调模型。

    产物**不自动入库**——转换与入库分两步是设计要求（链外准备＋人工核对）。
    """
    path: Path = args.path
    if not path.is_file():
        print(f"转换失败：路径不存在或不是文件 → {path}", file=sys.stderr)
        return 1

    out: Path = args.out if args.out is not None else path.with_suffix(".md")
    try:
        markdown, conversion = convert_html_file(
            path,
            source=args.source,
            applicable_scope=args.scope,
            license_note=args.license_note,
        )
    except (OSError, ValueError) as exc:
        print(f"转换失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        print(f"转换失败：写文件失败 {type(exc).__name__}", file=sys.stderr)
        return 1

    print(f"已转换：{path}")
    print(f"  输出：{out}")
    print(f"  正文容器：{conversion.container}")
    print(f"  字符数：{len(conversion.markdown)}")
    print(f"  元数据键：{', '.join(conversion.metadata) or '（无）'}")
    if conversion.images_dropped:
        print(f"  ⚠ 丢弃图片 {conversion.images_dropped} 张（已在原位留痕，不静默丢）", file=sys.stderr)
    if conversion.container == "body":
        print("  ⚠ 未找到 <article>/<main>，退回 <body>——正文可能含导航，需人工复核", file=sys.stderr)
    print("  提示：这是**待审**产物——核对标题层级与表格后再 ingest（RAG 策略第 1.1 节）")
    return 0


async def _run_ingest(args: argparse.Namespace) -> int:
    """执行摄取：一份文件一个事务（失败即整份回滚）。"""
    settings = get_settings()
    path: Path = args.path

    if not path.is_file():
        print(f"摄取失败：路径不存在或不是文件 → {path}", file=sys.stderr)
        return 1

    engine = create_engine(settings)
    async_engine_holder = engine
    sync_engine = None
    try:
        # 框架要求同步与异步引擎同时注入；同步引擎仅服务于它的写入路径。
        from campfire.core.db import create_sync_engine

        sync_engine = create_sync_engine(settings)
        vector_store = build_vector_store(settings, engine=sync_engine, async_engine=async_engine_holder)

        # 一份文件一个事务：条目表与节点表同事务落库（RAG 策略第 2、7 节）。
        async with session_scope(settings) as session:
            result = await ingest_file(
                settings,
                session,
                vector_store=vector_store,
                path=path,
                title=args.title,
                source=args.source,
                applicable_scope=args.scope,
                keywords=args.keywords,
                aliases=args.aliases,
            )
    except EmbeddingConfigurationError as exc:
        print(f"摄取失败：{exc}", file=sys.stderr)
        return 1
    except IngestionError as exc:
        print(f"摄取失败：{exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
        if sync_engine is not None:
            sync_engine.dispose()

    if result.skipped:
        print(f"跳过（内容未变）：{result.source_path}")
    else:
        print(f"已摄取：{result.source_path}")
        print(f"  条目 id：{result.item_id}")
        print(f"  写入节点：{result.chunks_written}")
    if result.needs_manual_review:
        # 不静默截断：明确告知有人工处理队列（RAG 策略第 1.2 节）。
        print(f"  ⚠ 需人工处理（超限且不可分，未嵌入）：{result.needs_manual_review} 块", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    """入口点。返回退出码而不是 ``sys.exit``，便于测试直接断言。"""
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "convert":
        return _run_convert(args)

    if args.command == "ingest":
        return asyncio.run(_run_ingest(args))

    print(_USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
