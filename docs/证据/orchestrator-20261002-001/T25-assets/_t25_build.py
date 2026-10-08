"""T25 资产生成器（临时工具，不进仓库脚本目录）。

它做两件事，两件事都**从 `git show HEAD:...` 的原始内容派生**——不手改、不靠记忆：

- `after`   ：在 `/readyz` 那一块之后插入 `location = /readyz/deep`（本包要交付的改动）；
- `ablated` ：同一份内容里**只**删掉那条 location 的 4 行（保留注释），即消融输入。

统一写 LF：宿主机 `core.autocrlf` 会把工作区写成 CRLF，而 git 归一化后两者相等
（实测：LF 与 CRLF 两份 `git diff` 都为空）。实验输入用 LF 是为了让
「修前/修后/消融」三份的字节差异**只来自那 4 行**，没有行尾噪音。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: 本文件在 `<repo>/.tmp/dev-orchestrator/20261002-001/T25-assets/` 下，因此仓库根是
#: `parents[4]`。按**特征**复核一次（与 `test_nginx_probe_routes.py` 同一处置）：
#: 层数写错会静默指向别的目录，而 `git show` 在那里会以 128 失败、看起来像 git 的问题。
REPO = Path(__file__).resolve().parents[4]
assert (REPO / "pyproject.toml").is_file() and (REPO / "infrastructure").is_dir(), f"仓库根定位错了：{REPO}"
REL = "infrastructure/docker/app-locations.conf"

COMMENT_BLOCK = """# 深度就绪探针（`campfire.main` 的 `/readyz/deep`）：按需调用，**不进周期健康检查**。
#
# **为什么必须是独立一条**：上面那条用的是 `location =`，即**精确匹配**——它只匹配
# `/readyz` 这一个 URI，**不覆盖任何子路径**。因此缺了本块时 `/readyz/deep` 会落到
# 最下面的 SPA `location /`，被 `try_files` 回成 `index.html` ⇒ **HTTP 200 + HTML**。
# 这比 404 更难辨认：404 说明「没有这个端点」，而 200 看起来像「端点通了」，调用方会把
# 一页 HTML 读成「深探针可用」。已实测（2026-10-05：本文件不含本块时 `/readyz/deep`
# 回 `Content-Type: text/html` + SPA 正文，`/readyz` 回 `application/json`）。
#
# **为什么不能再加进任何周期健康检查**（成本纪律，`campfire.main` 的 docstring 有同一论证）：
# 它会**真的调用一次供应商的嵌入端点**（这是它存在的全部理由——`/readyz` 的 `model` 项
# 只探 chat 端点，抓不到嵌入链路的参数级缺陷）。生产 healthcheck 是**每 15 秒**一次，
# 放进去约等于 **5760 次/天**的配额消耗。因此它只在**发布验收与人工诊断**时按需调用；
# `docker-compose.prod.yml`、CD 的发布轮询与 `scripts/acceptance_probe.py` 都继续用 `/readyz`。
"""

LOCATION_BLOCK = """location = /readyz/deep {
    proxy_pass         http://$campfire_api;
    proxy_set_header   Host $host;
    add_header         Cache-Control "no-store" always;
}
"""

HEADER_NOTE_OLD = """# 注意这三个 location 都是**反代到后端**的，因此它们证明的是「nginx + 后端」，
# 不是「nginx 自己」。web 容器的 healthcheck 需要后者——见下面 `/nginx-health`。"""

HEADER_NOTE_NEW = """# 注意这几个探针 location 都是**反代到后端**的，因此它们证明的是「nginx + 后端」，
# 不是「nginx 自己」。web 容器的 healthcheck 需要后者——见下面 `/nginx-health`。
#
# 分两类，判据不同（`/readyz/deep` 那一类见它自己上方的注释）：
#   - `/livez`、`/readyz`、`/health`：**周期性**判据（容器 healthcheck、CD 发布轮询）；
#   - `/readyz/deep`：**按需**判据（发布验收、人工诊断），因为它有配额成本。"""

ANCHOR = "location = /readyz {\n    proxy_pass         http://$campfire_api;\n    proxy_set_header   Host $host;\n    add_header         Cache-Control \"no-store\" always;\n}\n"


def head_text() -> str:
    raw = subprocess.run(
        ["git", "show", f"HEAD:{REL}"],
        cwd=REPO,
        check=True,
        capture_output=True,
    ).stdout
    return raw.decode("utf-8").replace("\r\n", "\n")


def build_after() -> str:
    text = head_text()
    assert text.count(ANCHOR) == 1, f"锚点不唯一：{text.count(ANCHOR)}"
    assert HEADER_NOTE_OLD in text, "头部说明的原文对不上（HEAD 变了？）"
    text = text.replace(HEADER_NOTE_OLD, HEADER_NOTE_NEW)
    return text.replace(ANCHOR, ANCHOR + COMMENT_BLOCK + LOCATION_BLOCK)


def build_ablated() -> str:
    """消融：只删掉那条 location 的 4 行，注释与其余一切都保留。"""
    text = build_after()
    assert text.count(LOCATION_BLOCK) == 1, "location 块不唯一"
    return text.replace(LOCATION_BLOCK, "")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("用法: _t25_build.py {after|ablated} <输出路径>", file=sys.stderr)
        return 2
    mode, out = argv[1], Path(argv[2])
    builders = {"after": build_after, "ablated": build_ablated}
    if mode not in builders:
        print(f"未知模式 {mode}", file=sys.stderr)
        return 2
    content = builders[mode]()
    out.write_bytes(content.encode("utf-8"))
    print(f"{mode} -> {out} ({len(content.encode('utf-8'))} bytes, LF)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
