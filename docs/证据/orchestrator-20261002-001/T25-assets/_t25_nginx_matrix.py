"""T25 nginx 行为验证驱动：换一份 app-locations.conf 进 harness 容器，抓原始 `curl -i`。

为什么要有这个脚本而不是手敲 curl：
「修前 / 修后 / 消融」三组的**唯一**输入差异必须是那份 conf。手工流程里最容易出的错是
「重启容器时忘了改挂载的文件」，于是第二组其实在重复第一组，而结论看起来照旧成立。
本脚本把「重启 → 等就绪 → 抓一组 curl → 打印状态行与 Content-Type」写死，并在每组
开头打印**容器实际读到的 conf 的 SHA256**（`docker exec sha256sum`）——那是「装进去的
是哪一份」的机器读数，不是我的一句声明。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
ASSETS = Path(__file__).resolve().parent
CONTAINER = "t25-harness-nginx"

VARIANTS = {
    "before": ASSETS / "app-locations.before.conf",
    "after": ASSETS / "app-locations.after.conf",
    "ablated": ASSETS / "app-locations.ablated.conf",
}

PATHS = ["/livez", "/readyz", "/readyz/deep", "/definitely-not-declared", "/nginx-health"]


def _run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=False, **kw)  # type: ignore[arg-type]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def start(variant: str) -> None:
    source = VARIANTS[variant]
    _run(["docker", "rm", "-f", CONTAINER])
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER,
        "--network",
        "t25-net",
        "-p",
        "8600:80",
        "-v",
        f"{REPO / 'infrastructure' / 'docker' / 'nginx.conf'}:/etc/nginx/nginx.conf:ro",
        "-v",
        f"{source}:/etc/nginx/app-locations.conf:ro",
        "-v",
        f"{ASSETS / 'html'}:/usr/share/nginx/html:ro",
        "-v",
        f"{ASSETS / 'empty' / 'ssl.d'}:/etc/nginx/ssl.d:ro",
        "-v",
        f"{ASSETS / 'empty' / 'redirect.d'}:/etc/nginx/redirect.d:ro",
        "-v",
        f"{ASSETS / 'empty' / 'certbot'}:/var/www/certbot:ro",
        "nginx:1.27-alpine",
    ]
    result = _run(cmd)
    assert result.returncode == 0, f"容器起不来：{result.stderr}"


def wait_ready(attempts: int = 30) -> None:
    import time

    for _ in range(attempts):
        probe = _run(["curl.exe", "-sS", "-o", "NUL", "--noproxy", "*", "--max-time", "3", "http://127.0.0.1:8600/livez"])
        if probe.returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("harness nginx 在 15 秒内没起来")


def capture(variant: str) -> list[str]:
    lines: list[str] = []
    conf_sha_in_container = _run(["docker", "exec", CONTAINER, "sha256sum", "/etc/nginx/app-locations.conf"]).stdout.split()[0]
    nginx_t = _run(["docker", "exec", CONTAINER, "nginx", "-t"])
    lines.append(f"### 变体 {variant}")
    lines.append(f"### 宿主侧文件      : {VARIANTS[variant]}")
    lines.append(f"### SHA256(宿主文件): {sha256_file(VARIANTS[variant])}")
    lines.append(f"### SHA256(容器内)  : {conf_sha_in_container}")
    lines.append(f"### nginx -t        : exit={nginx_t.returncode}")
    lines.append((nginx_t.stderr or nginx_t.stdout).strip())
    for path in PATHS:
        result = _run(["curl.exe", "-sS", "-i", "--noproxy", "*", "--max-time", "10", f"http://127.0.0.1:8600{path}"])
        body_header = result.stdout.splitlines()
        status = body_header[0] if body_header else "(无响应)"
        ctype = next((ln for ln in body_header if ln.lower().startswith("content-type:")), "(无 Content-Type)")
        lines.append("")
        lines.append(f"### curl -i --noproxy '*' http://127.0.0.1:8600{path}")
        lines.append(result.stdout.rstrip())
        lines.append(f"---- 摘要: {status} | {ctype}")
    return lines


def main(argv: list[str]) -> int:
    variants = argv[1:] or ["before", "after", "ablated"]
    out: list[str] = [f"=== T25 nginx 行为验证：原始 curl -i 输出（变体：{', '.join(variants)}） ==="]
    for variant in variants:
        start(variant)
        wait_ready()
        out.extend(capture(variant))
        out.append("")
    target = ASSETS / "evidence-nginx-matrix.txt"
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    print(f"\n已落盘：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
