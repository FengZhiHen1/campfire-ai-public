"""T25 反向消融：把 `/readyz/deep` **从应用侧的参考集合里拿掉**，守卫会怎样？

任务包要求：「并（若可行）从应用侧删掉端点 ⇒ 也应红/或说明为何不」。

**为什么不能真的删 `main.py` 的端点**：`apps/api/src/campfire/**` 是本包明令不许改的文件
（T19/T20/T21/T22 正在改）。本机 `main.py` 已有 20 处未提交改动。

**⇒ 本脚本用「直接调用守卫的两个纯函数、喂一个不含 `/readyz/deep` 的参考集合」来演示它的
语义**。如实标注其证据强度：**这是对判据语义的演示，不是端到端消融**——它不经过
`campfire.main.app.routes`，所以它证明的是「参考集合少一条时判据怎么走」，
不是「改掉 main.py 之后 pytest 会怎样」。

对照第一组（`before`：参考集合含 `/readyz/deep`、配置里没有 ⇒ 红）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
ASSETS = Path(__file__).resolve().parent
TEST_FILE = REPO / "apps" / "api" / "tests" / "test_nginx_probe_routes.py"
CONF = REPO / "infrastructure" / "docker" / "app-locations.conf"


def _load_guard():  # noqa: ANN202 —— 动态加载的测试模块，无公开类型
    spec = importlib.util.spec_from_file_location("t25_guard", TEST_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["t25_guard"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    guard = _load_guard()
    declared = guard._nginx_locations(CONF.read_text(encoding="utf-8"))
    real = sorted(guard._registered_probe_paths())

    print(f"真实参考集合（来自 campfire.main.app.routes）：{real}")
    print(f"配置里已声明的路径：{sorted(declared)}")
    print()

    scenarios = {
        "参考集合 = 真实集合（含 /readyz/deep）": real,
        "参考集合 去掉 /readyz/deep（模拟应用侧删端点）": [p for p in real if p != "/readyz/deep"],
    }
    for label, probes in scenarios.items():
        missing = guard._undeclared_probe_paths(probes, declared)
        verdict = "红（报缺 location）" if missing else "绿（无缺失）"
        print(f"  {label}")
        print(f"    -> {verdict}；missing={missing}")
    print()
    print("说明：本脚本只喂参考集合，不经过 pytest 断言层，因此上表的「红/绿」是")
    print("**判据函数的返回值**，不是用例的通过/失败。端到端消融见 evidence-ablation.txt。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
