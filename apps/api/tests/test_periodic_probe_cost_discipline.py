"""成本纪律守卫：**任何周期健康检查都不得引用按需端点**（`/readyz/deep`）。

## 为什么有这个文件（它补的是一个"没有任何东西会失败"的缺口）

`/readyz/deep` 会**真的调用一次供应商的嵌入端点**（那正是它存在的理由——
`/readyz` 的 `model` 项只探 chat，抓不到嵌入链路的参数级缺陷）。
生产 healthcheck 是**每 15 秒**一次 ⇒ **若有人把它指向 `/readyz/deep`，
配额消耗约 5760 次/天**。

**⇒ 而这个"若有人"目前【没有任何东西会拦住】**：
`:19` 的 T19 复查者把这条记为 P2 并建议补一个机械检查，编排器采纳。
**⇒ 本文件就是那个检查。**

## 判据设计（防"永不失败的检查"的四条，与 T22/T25 的守卫同模式）

1. **数据源 = 仓库里的真实配置文本**（不是硬编码清单）——
   **全仓扫描**健康检查/轮询定义，**而不是只盯三份已知文件**：
   只盯已知文件的话，**将来新增第四个 healthcheck 时不会红**；
2. **反空断言**：**若一个探针 URL 都没扫到 ⇒ 必须失败**（表达式写错会让它静默恒真）；
3. **判别性自测**：喂一份**人为含 `/readyz/deep`** 的合成配置 ⇒ **断言真的报错**；
4. **针对根因形态**：本条根因是"周期 × 按需"的混淆，
   所以断言的是**「周期定义里不得出现按需端点」**这个语义，
   而不是"某个文件里没有某个字符串"。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

#: 按需端点：**只在发布验收/人工诊断时调用**，会真实消耗嵌入配额。
ON_DEMAND_PROBE_PATH = "/readyz/deep"

#: 周期端点：可以进 healthcheck / 发布轮询（免费或极廉价）。
PERIODIC_PROBE_PATHS = ("/readyz", "/livez", "/health", "/nginx-health")

_REPO_ROOT_MARKERS = ("pyproject.toml", "scripts")


def _find_repo_root() -> Path:
    """向上找仓库根：同时含 `pyproject.toml` 与 `scripts/` 的那一层。

    不写死 `parents[N]`：层数会随目录调整静默指错位置（本仓有一次实际教训）。
    """
    for path in Path(__file__).resolve().parents:
        if all((path / marker).exists() for marker in _REPO_ROOT_MARKERS):
            return path
    raise RuntimeError(f"未能从 {Path(__file__).resolve()} 向上找到仓库根")


REPO_ROOT = _find_repo_root()

#: 要扫描的"周期检查定义"所在文件（相对仓库根）。
#:
#: ⚠ 为什么是**扫描**而不是硬编码断言：见模块 docstring 第 1 条。
#: 这些是当前已知的承载位置；扫描逻辑本身对"新增位置"也生效
#: （只要它在下面这些扩展名与目录里）。
_SCAN_ROOTS = ("docker-compose.yml", "docker-compose.prod.yml", "infrastructure", ".github", "scripts")
_SCAN_SUFFIXES = (".yml", ".yaml", ".sh", ".py", ".conf")


#: 编码为 UTF-8 读取；读不了的（二进制等）跳过。
def _iter_scan_files() -> list[Path]:
    """列出要扫描的文件（存在且后缀匹配）。"""
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        target = REPO_ROOT / root
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(path for path in target.rglob("*") if path.is_file() and path.suffix in _SCAN_SUFFIXES)
    return sorted(files)


def probe_urls_in(text: str) -> set[str]:
    """从一段配置/脚本文本里抽出所有运维探针 URL 路径。

    识别两种写法：
    1. 裸路径：`/readyz/deep`、`/readyz`、`/livez`、`/health`、`/nginx-health`；
    2. URL 形式：`http://host:8000/readyz`（抽 path 部分）。

    ⚠ 只认"探针族"的路径（上面 `PERIODIC_PROBE_PATHS` + 按需端点 + 其子路径），
    避免把 `/api/...` 之类误算成探针。
    """
    found: set[str] = set()
    # 裸路径与 URL 内的路径都能被这条抓：`/readyz` 与 `/readyz/deep`
    for match in re.finditer(r"/(?:readyz|livez|health|nginx-health)(?:/[\w-]+)*", text):
        found.add(match.group(0))
    return found


def periodic_context_violations(text: str) -> list[str]:
    """在一段文本里找出「周期检查上下文中引用了按需端点」的行。

    判据：**只要该行同时出现按需端点，且它处在周期检查的载体里**
    （`healthcheck` / `test:` / `curl` / `CMD-SHELL` / `probe` / `slug` / `liveness` / `readiness`），
    就判违规。

    ⚠ 这是**保守**的：注释、文档字符串里提到端点**不算违规**
    （本仓大量注释在解释这个端点，那些不该红）。
    ⇒ 判定方式：**按行**匹配"周期载体关键词"，**注释行（以 `#` 开头）跳过**。
    """
    violations: list[str] = []
    periodic_markers = (
        "healthcheck",
        "test:",
        "cmd-shell",
        "curl ",
        "probe",
        "liveness",
        "readiness",
    )
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        lowered = line.lower()
        if ON_DEMAND_PROBE_PATH not in line:
            continue
        if not any(marker in lowered for marker in periodic_markers):
            continue
        violations.append(f":{line_no} {line[:100]}")
    return violations


class TestGuardGoesRedOnSyntheticInput:
    """判别性自测：**先证明这个判据真的会红**，再去扫真实仓库。

    ⚠ 没有这一组，下面的"全仓无违规"可能是一条恒真的空闸门
    （例如正则失配 ⇒ 一条都没扫到 ⇒ 自然"没有违规"）。本项目的纪律如此。
    """

    def test_docker_compose_healthcheck_with_on_demand_endpoint_is_flagged(self) -> None:
        """合成一份把 healthcheck 指向按需端点的 compose 片段 ⇒ 必须报出。"""
        synthetic = (
            "services:\n"
            "  api:\n"
            "    healthcheck:\n"
            '      test: ["CMD-SHELL", "curl -fsS --max-time 5 http://127.0.0.1:8000/readyz/deep || exit 1"]\n'
        )
        violations = periodic_context_violations(synthetic)
        assert violations, "判据对『healthcheck 指向按需端点』无感 ⇒ 它是空闸门"

    def test_curl_in_deploy_step_with_on_demand_endpoint_is_flagged(self) -> None:
        """合成一份发布轮询脚本 ⇒ 必须报出。"""
        synthetic = 'curl -fsS "$BASE/readyz/deep" || exit 1\n'
        assert periodic_context_violations(synthetic), "发布轮询指向按需端点未被发现"

    def test_comment_explaining_the_endpoint_is_not_flagged(self) -> None:
        """**注释里提到它不算违规** —— 本仓大量注释在解释它，误报会让人忽略这个闸门。"""
        synthetic = "# 注意：不要把 healthcheck 指向 /readyz/deep（每 15 秒一次 = 5760 次/天）\n"
        assert periodic_context_violations(synthetic) == []

    def test_periodic_endpoint_in_healthcheck_is_fine(self) -> None:
        """周期端点出现在 healthcheck 里是**正确的**，不该红。"""
        synthetic = '    test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8000/readyz || exit 1"]\n'
        assert periodic_context_violations(synthetic) == []


class TestProbeUrlExtraction:
    """`probe_urls_in` 的抽取必须能命中（否则全仓扫描恒为空）。"""

    def test_extracts_on_demand_endpoint(self) -> None:
        assert ON_DEMAND_PROBE_PATH in probe_urls_in("curl http://h:8000/readyz/deep")

    def test_extracts_periodic_endpoints(self) -> None:
        found = probe_urls_in("curl -fsS /readyz; curl /livez; curl /nginx-health")
        assert {"/readyz", "/livez", "/nginx-health"} <= found

    def test_ignores_non_probe_paths(self) -> None:
        """业务路径不该被误算成探针（否则会产生无关的噪声与误判）。"""
        assert probe_urls_in("curl http://h:8000/api/consult/sessions") == set()


class TestRepositoryHasNoPeriodicConsumerOfOnDemandEndpoint:
    """★ 主判据：全仓**不得存在**任何周期检查引用按需端点。"""

    def test_scan_finds_probe_definitions(self) -> None:
        """**反空断言**：扫描必须真的看到探针定义。

        ⚠ 若这里红了，说明扫描范围/正则坏了 ⇒ **此时"全仓无违规"毫无意义**。
        这正是"0 命中需要正例担保"（本项目登记过三次的坑）。
        """
        scanned = 0
        probe_hits = 0
        for path in _iter_scan_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            scanned += 1
            if probe_urls_in(text):
                probe_hits += 1
        assert scanned > 0, "一个文件都没扫到 ⇒ 扫描范围写错了"
        assert probe_hits > 0, (
            f"扫了 {scanned} 个文件但一个探针路径都没抽到 ⇒ 正则或范围坏了，"
            "此时『无违规』是假绿（本项目的『永远不失败的检查』形态）"
        )

    def test_no_periodic_check_references_the_on_demand_endpoint(self) -> None:
        """全仓扫描：任何周期检查都不得引用 `/readyz/deep`。"""
        all_violations: list[str] = []
        for path in _iter_scan_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for violation in periodic_context_violations(text):
                rel = path.relative_to(REPO_ROOT).as_posix()
                all_violations.append(f"{rel}{violation}")

        assert not all_violations, (
            "以下周期检查引用了按需端点 `/readyz/deep` —— "
            "它会真实消耗嵌入配额（每 15 秒一次 ≈ 5760 次/天）：\n  "
            + "\n  ".join(all_violations)
            + "\n⇒ 周期检查请用 `/readyz`（免费）；`/readyz/deep` 只在发布验收/人工诊断时按需调用。"
        )

    def test_compose_healthchecks_only_use_periodic_endpoints(self) -> None:
        """**针对性断言 compose 的 healthcheck 块**（本缺陷最可能的落点）。

        与上一条的区别：这条**只读 compose**，因此当有人改动它时，
        失败信息会直接指向那份文件（上一条是全局兜底）。
        """
        compose = REPO_ROOT / "docker-compose.prod.yml"
        assert compose.is_file(), f"找不到 {compose}"
        text = compose.read_text(encoding="utf-8")
        hosts = [line.strip() for line in text.splitlines() if ON_DEMAND_PROBE_PATH in line]
        offending = [line for line in hosts if not line.startswith("#")]
        assert not offending, "`docker-compose.prod.yml` 里出现了按需端点（应只出现在注释里）：\n  " + "\n  ".join(
            offending
        )


if __name__ == "__main__":  # pragma: no cover - 手动运行时给个可读摘要
    raise SystemExit(pytest.main([__file__, "-v"]))
