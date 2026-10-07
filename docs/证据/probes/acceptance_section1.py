"""上线验收：第 1 节（静态与基础设施）——可脚本化的部分。

依据 docs/运维/上线验收测试流程.md 第 1 节。判据与文档逐条对应，
不额外发明标准。

**为什么这些能脚本化而登录之后的部分不能**：第 1 节只依赖 HTTP 语义
（状态码、Content-Type、响应体形状）；第 2 节起依赖 httpOnly cookie 与
anti-CSRF 自定义头，`curl`/`urllib` 走不完整，必须用真实浏览器。

关于 443：当前云安全组未放行，因此默认走 HTTP。用 `--base` 可切换。
"""

import argparse
import json
import re
import urllib.error
import urllib.request

PAGES = [
    "/", "/login", "/consult", "/consult/emergency", "/profile",
    "/cases", "/settings", "/settings/memory", "/guide",
]
PROTECTED_APIS = [
    "/api/consult/sessions", "/api/profile/objects",
    "/api/memory/episodes", "/api/library/items",
]


def probe(base: str, path: str) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(base + path, timeout=20) as response:
            return response.status, response.headers.get("Content-Type", "?"), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "?"), exc.read()
    except Exception as exc:  # noqa: BLE001 —— 探针
        return 0, "?", f"{type(exc).__name__}: {exc}".encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://campfire.wenran.me")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    print(f"验收目标：{base}\n")
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'OK  ' if ok else 'FAIL'}] {label}{('  ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    print("=== 1.1 就绪探针 ===")
    status, _, body = probe(base, "/readyz")
    check("/readyz 返回 200", status == 200, f"HTTP {status}")
    try:
        report = json.loads(body)
        check("ready == true", report.get("ready") is True)
        expected = {"auth", "database", "queue", "model", "falkordb", "agent_assembly", "skills"}
        actual = set(report.get("components", {}))
        check("七项组件齐备", actual == expected, f"实际 {sorted(actual)}")
        for name, item in report.get("components", {}).items():
            check(f"  {name} == ok", item["status"] == "ok", item["detail"][:46])
    except Exception as exc:  # noqa: BLE001
        check("解析 /readyz", False, str(exc))

    print("\n=== 1.2 页面路由（应用 SPA，含深链）===")
    for path in PAGES:
        status, ctype, body = probe(base, path)
        text = body.decode("utf-8", "replace")
        ok = status == 200 and "text/html" in ctype and 'id="root"' in text
        check(f"{path:22}", ok, f"HTTP {status}")

    print("\n=== 1.3 静态资源（从首页 HTML 取真实路径）===")
    _, _, home = probe(base, "/")
    html = home.decode("utf-8", "replace")
    assets = sorted(set(re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)))
    check("首页引用了静态资源", len(assets) > 0, f"{len(assets)} 个")
    for asset in assets:
        status, ctype, body = probe(base, asset)
        expect = "javascript" if asset.endswith(".js") else "css" if asset.endswith(".css") else ""
        ok = status == 200 and (not expect or expect in ctype)
        check(f"{asset[:46]:48}", ok, f"HTTP {status} {ctype} {len(body)}B")

    print("\n=== 1.4 未登录访问边界（应全部 401）===")
    for path in PROTECTED_APIS:
        status, _, _ = probe(base, path)
        check(f"{path:28}", status == 401, f"HTTP {status}")

    print()
    if failures:
        print(f"未通过 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
    else:
        print(f"第 1 节全部通过（{len(PAGES)} 页面 + {len(assets)} 资源 + {len(PROTECTED_APIS)} 边界）")


main()
