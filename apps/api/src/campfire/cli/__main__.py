"""``python -m campfire.cli`` 的入口。

设计（RAG 策略第 7 节）把摄取定成**应用包内的一个 CLI 入口**，跑在同一镜像里、
连同一个库；**不暴露成服务端点**。提取逻辑归 ``modules/library``（检索链与摄取
同属一个模块），本入口只负责命令行形态、参数解析与退出码。

用法::

    python -m campfire.cli ingest <路径> --source <出处> --scope <适用范围>

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
from campfire.modules.library.ingestion import (
    IngestionError,
    build_vector_store,
    ingest_file,
)

_USAGE = """campfire.cli —— 本地运维入口（不暴露成服务端点）

子命令：
  ingest <路径>   摄取处理好的 Markdown 文件到资料库

示例：
  python -m campfire.cli ingest docs/guide.md --source "WHO 2024" --scope "学龄前儿童"
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m campfire.cli", description="篝火智答本地运维入口")
    sub = parser.add_subparsers(dest="command")

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

    if args.command == "ingest":
        return asyncio.run(_run_ingest(args))

    print(_USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
