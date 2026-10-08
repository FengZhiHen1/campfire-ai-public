"""T25 消融实验驱动：把某一份配置装进工作区，跑守卫，报告退出码，再恢复交付版。

为什么用脚本而不是手敲几条 `Copy-Item`：
实验的可信度取决于「两次运行之间**只有**被测变量不同」。手敲容易漏掉把上一次的
文件恢复干净，于是第二组跑在一个混合状态上，而它的结论看起来仍然成立。
本脚本把「装哪一份 → 跑什么 → 怎么恢复」写死，并打印每次的 SHA256 作为可复核的锚点。
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
ASSETS = Path(__file__).resolve().parent
TARGET = REPO / "infrastructure" / "docker" / "app-locations.conf"

VARIANTS = {
    "before": ASSETS / "app-locations.before.conf",
    "after": ASSETS / "app-locations.after.conf",
    "ablated": ASSETS / "app-locations.ablated.conf",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_guard(label: str) -> int:
    print(f"\n{'=' * 78}\n### 变体 {label}：{TARGET.name} SHA256={sha(TARGET)}")
    print(f"{'=' * 78}")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "apps/api/tests/test_nginx_probe_routes.py",
            "-v",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO,
    )
    print(f"### {label} 的 pytest 退出码 = {proc.returncode}")
    return proc.returncode


def main(argv: list[str]) -> int:
    names = argv[1:] or ["after", "before", "after"]
    results: list[tuple[str, int]] = []
    for name in names:
        source = VARIANTS[name]
        shutil.copyfile(source, TARGET)
        results.append((name, run_guard(name)))

    # 恢复到交付版（本包要留下的状态）
    shutil.copyfile(VARIANTS["after"], TARGET)
    print(f"\n{'=' * 78}\n### 已恢复交付版：SHA256={sha(TARGET)}")
    print(f"{'=' * 78}")
    print("\n汇总：")
    for name, code in results:
        verdict = "绿（退出码 0）" if code == 0 else f"红（退出码 {code}）"
        print(f"  {name:<10} -> {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
