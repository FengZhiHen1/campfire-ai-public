"""上线验收（可脚本化的部分）：静态资源、页面深链、未登录边界。

用法：
    uv run --no-project python scripts/acceptance_probe.py --base https://campfire.wenran.me

依据 docs/运维/上线验收测试流程.md 第 1 节，判据与该文档逐条对应，不额外发明标准。

为什么只覆盖第 1 节：这一节只依赖 HTTP 语义（状态码、Content-Type、响应体形状），
因此可以用脚本判定。第 2 节起需要真实登录态——依赖 httpOnly cookie 与 anti-CSRF
自定义头，urllib 走不完整，必须用真实浏览器（见该文档「附：本流程的证据边界」）。

为什么这些判据不是「200 就算过」：
  - 页面要逐个直连，不能只从首页点进去。客户端路由不会触发深链请求，而 nginx 的
    location 优先级问题只在直连时暴露（本项目真的踩过：/consult、/profile 被 API
    前缀截走，返回 JSON 404）；
  - 静态资源要查 MIME。Content-Type 错了会白屏，而状态码仍是 200；
  - 就绪用 /readyz 而不是 /livez。后者只看进程活着——一个「Agent 装配失败、核心端点
    必回 503」的版本在它眼里完全健康。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

# 全部需要登录的页面。逐个直连（不是从首页导航）——理由见模块 docstring。
PAGES = [
    "/",
    "/login",
    "/consult",
    "/consult/emergency",
    "/profile",
    "/cases",
    "/settings",
    "/settings/memory",
    "/guide",
]

# 未登录访问应一律 401。404 说明路由没挂上，200 说明鉴权漏了——三者含义完全不同。
PROTECTED_APIS = [
    "/api/consult/sessions",
    "/api/profile/objects",
    "/api/memory/episodes",
    "/api/library/items",
]

# /readyz 的七项探针。少一项或多一项都算失败：前者是覆盖退化，后者是契约变更未同步。
EXPECTED_PROBES = {"auth", "database", "queue", "model", "falkordb", "agent_assembly", "skills"}


def probe(base: str, path: str) -> tuple[int, str, bytes]:
    """发一个 GET，返回 (状态码, Content-Type, 响应体)。

    不抛异常：探测的目标就是「拿到什么」，网络失败也应当被记录成一次失败而非中断整轮。
    """
    request = urllib.request.Request(
        base + path,
        headers={"User-Agent": "campfire-acceptance-probe"},
    )
    # 直连：本机若有 TUN 代理会拦部分目标，导致误判。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=25) as response:
            return response.status, response.headers.get("Content-Type", "?"), response.read()
    except urllib.error.HTTPError as exc:
        # 4xx/5xx 是预期的探测结果之一（正是要区分 401/404/200），不是异常。
        return exc.code, exc.headers.get("Content-Type", "?"), exc.read()
    except Exception as exc:  # noqa: BLE001 —— 探测本身要能容错
        return 0, "?", f"{type(exc).__name__}: {exc}".encode()


def main() -> int:
    """跑完四组检查并返回退出码（0 = 全过，1 = 有失败）。

    退出码是给 CI/脚本用的判据，不是装饰：它让「验收没过」能被自动拦住，
    而不是要人去看输出里有没有 FAIL。
    """
    parser = argparse.ArgumentParser(description="上线验收探测（第 1 节）")
    parser.add_argument(
        "--base",
        default="https://campfire.wenran.me",
        help="目标站点根（默认生产 HTTPS）",
    )
    args = parser.parse_args()
    base = args.base.rstrip("/")

    print(f"验收目标：{base}\n")
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        """记录一条判据结果；失败时登记到 failures，供最后的退出码使用。"""
        print(f"  [{'OK  ' if ok else 'FAIL'}] {label}{('  ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    print("=== 1.1 就绪探针 ===")
    status, _, body = probe(base, "/readyz")
    check("/readyz 返回 200", status == 200, f"HTTP {status}")
    try:
        report = json.loads(body)
        check("ready == true", report.get("ready") is True)
        actual = set(report.get("components", {}))
        check("七项组件齐备", actual == EXPECTED_PROBES, f"实际 {sorted(actual)}")
        for name, item in report.get("components", {}).items():
            check(f"  {name} == ok", item["status"] == "ok", str(item.get("detail", ""))[:46])
    except Exception as exc:  # noqa: BLE001
        check("解析 /readyz", False, str(exc))

    print("\n=== 1.2 页面路由（应用 SPA，含深链）===")
    for path in PAGES:
        status, ctype, page_body = probe(base, path)
        text = page_body.decode("utf-8", "replace")
        # 判据三条同时成立：状态 200、是 HTML、含 SPA 挂载点。
        # 只看 200 会让「API 返回的 JSON 404」漏过——那是真的踩过的缺陷。
        ok = status == 200 and "text/html" in ctype and 'id="root"' in text
        check(f"{path:22}", ok, f"HTTP {status}")

    print("\n=== 1.3 静态资源（从首页 HTML 取真实路径）===")
    _, _, home = probe(base, "/")
    html = home.decode("utf-8", "replace")
    assets = sorted(set(re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)))
    check("首页引用了静态资源", len(assets) > 0, f"{len(assets)} 个")
    for asset in assets:
        status, ctype, asset_body = probe(base, asset)
        expect = "javascript" if asset.endswith(".js") else "css" if asset.endswith(".css") else ""
        ok = status == 200 and (not expect or expect in ctype)
        check(f"{asset[:46]:48}", ok, f"HTTP {status} {ctype} {len(asset_body)}B")

    print("\n=== 1.4 未登录访问边界（应全部 401）===")
    for path in PROTECTED_APIS:
        status, _, _ = probe(base, path)
        check(f"{path:28}", status == 401, f"HTTP {status}")

    print()
    if failures:
        print(f"未通过 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"第 1 节全部通过（{len(PAGES)} 页面 + {len(assets)} 资源 + {len(PROTECTED_APIS)} 边界）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
