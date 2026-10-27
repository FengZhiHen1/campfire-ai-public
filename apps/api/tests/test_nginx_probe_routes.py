"""Nginx 路由守卫：应用真实注册的运维探针路径，每一条都必须在 `app-locations.conf` 里有 location。

## 这个文件存在的理由

`infrastructure/docker/app-locations.conf` 是**路由契约**，但它不是代码，此前没有任何
测试覆盖它。2026-10-05 因此漏掉了一条：`/readyz/deep`（`campfire.main` 新增的按需深探针）
**没有** location，于是落到 SPA 的 `location /`、被 `try_files` 回成 `index.html`
⇒ **HTTP 200 + HTML**。**这比 404 更难辨认**：404 说明「没有这个端点」，而 200 看起来像
「端点通了」，调用方会把一页 HTML 读成「深探针可用」。实测原文（修前/修后 `curl -i` 对照）
见 原证物 `orchestrator-20261002-001/T25.md` 第 3 节。

## ★ 数据源为什么不是「永不失败的检查」

本守卫**不硬编码** `/readyz/deep` 这类名字，而是**从应用真实注册的路由表里读**
（`campfire.main.app.routes` 里的 `APIRoute`，取业务前缀 `/api` 之外的根级路径）。

- 硬编码断言（`assert "location = /readyz/deep" in conf`）的失效形态是：**新加端点时它
  不会红**——那正是本条缺陷的形态（T19 加了端点，没有任何东西会因此变红）。
- 本守卫的数据源随应用自动扩展：**新增一个根级探针端点而忘了加 location，它就会红**。
  这不是推测，本文件用两条用例把「它会红」钉死：
  `test_guard_goes_red_when_a_registered_probe_has_no_location`（判据本身能红）与
  `test_discovery_source_is_not_empty`（数据源取空时不许静默通过）。

## 为什么用 (a) pytest 而不是 (b) `scripts/` + CI 步骤

任务包给了两个载体，我选 **(a)**，三条理由都不是偏好：

1. **判据的数据源就是 Python 应用对象**（`campfire.main.app` 的路由表）。pytest 同进程
   直接 import；独立脚本要另起子进程并处理 `sys.path` / `.env` / 依赖，多一层失败面，
   而这一层失败与判据本身无关却会让守卫红——那样守卫会先被当成噪音关掉。
2. **判据的既有承载处就是 `apps/api/tests/`**：探针自身的形状由 `test_health.py` 钉住，
   探针的**路由可达性**与它同源。分成两处必然漂移（`app-locations.conf` 文件头第 4 条的
   论证同样适用于这里）。
3. **不需要动 CI 配置**：`ci.yml` 的 backend job 已经跑 `uv run pytest`，本用例自动进 CI。
   走 (b) 要给 `ci.yml` 加步骤，而 `deploy.yml` 的每一步都要 SSH 到生产，不该在那里放
   纯静态检查。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from fastapi.routing import APIRoute

from campfire import main as main_module

#: 反向自检用的**故意不存在**的探针路径（见本文件用例
#: `test_guard_goes_red_when_a_registered_probe_has_no_location`）。
#:
#: 为什么必须有一个：判据「每一个参考路径都有 location」在**参考集合为空**时恒真，
#: 而恒真的检查是本项目明令禁止的东西。这条路径给判据一个必然红、且与真实配置无关的输入。
_ABSENT_PROBE_PATH = "/readyz/this-endpoint-does-not-exist"

#: 业务接口的统一前缀（`campfire.main` 的同名常量）。探针**刻意不**在它下面。
_API_PREFIX = "/api"

#: 匹配 location 行：`location [修饰符] <路径> {`。
#:
#: 修饰符是可选捕获组（`=` 精确、`^~` 前缀优先、`~`/`~*` 正则），路径取到空白之前。
#: `location / {` 这种无修饰符写法也要认。
_LOCATION_RE = re.compile(
    r"^\s*location\s+(?:(?P<modifier>[=~^*]+)\s+)?(?P<path>\S+)\s*\{",
    re.MULTILINE,
)


def _find_repo_root() -> Path:
    """向上找仓库根：同时含 `pyproject.toml` 与 `infrastructure/` 的那一层。

    与 `test_periodic_probe_cost_discipline.py`（已于 2026-10-08 按用户裁决删除）
    同一处置、同一理由：
    **按特征定位而不是按层数**（`parents[N]` 在目录调整时会静默指向错误位置，
    那种失败看起来像「文件丢了」）。找不到立刻抛错，不返回一个猜测的路径。
    """
    required = ("pyproject.toml", "infrastructure")
    for path in Path(__file__).resolve().parents:
        if all((path / marker).exists() for marker in required):
            return path
    raise RuntimeError(f"未能在 {Path(__file__).resolve()} 的上级目录中找到仓库根")


_REPO_ROOT = _find_repo_root()
_LOCATIONS_CONF = _REPO_ROOT / "infrastructure" / "docker" / "app-locations.conf"


def _nginx_locations(text: str) -> dict[str, str]:
    """解析出「路径 → 修饰符」表（修饰符为空串表示无修饰符）。

    只认 `location` 行本身：**不解析 include、不展开嵌套语义**。本守卫要问的问题是
    「这个 URI 有没有被一条 location 认领」，而 nginx 的精确匹配（`location = /x`）
    与嵌套关系无关——嵌套 location 只影响前缀/正则的归属，不影响 `=` 的命中。
    """
    return {hit.group("path"): (hit.group("modifier") or "") for hit in _LOCATION_RE.finditer(text)}


def _registered_probe_paths() -> frozenset[str]:
    """★ 判据的数据源：应用**真实注册**的根级探针路径。

    取 `campfire.main.app.routes` 里 `APIRoute` 的子集，再排除业务前缀 `/api`——
    `main.py` 的 `_API_PREFIX` 注释写明「存活/就绪/诊断三个探针**不**加这个前缀」，
    因此「不在 `/api` 下的根级 APIRoute」就是「这个应用声明过的运维探针路径」。

    读真实路由表而不是维护一份清单：清单会漂移，而漂移的形态恰好是
    「新端点没进清单 ⇒ 守卫不红」（见文件头的论证）。
    """
    routes = getattr(main_module.app, "routes", ())
    return frozenset(
        route.path for route in routes if isinstance(route, APIRoute) and not route.path.startswith(_API_PREFIX)
    )


def _conf_text() -> str:
    return _LOCATIONS_CONF.read_text(encoding="utf-8")


def _undeclared_probe_paths(
    probe_paths: Iterable[str],
    declared: Mapping[str, str],
) -> list[str]:
    """参考路径里，哪些**没有**一条精确匹配（`location =`）的 location。

    为什么要求修饰符是 `=`：本文件现有的四个探针 location 全部是精确匹配，而
    `location /readyz/deep`（无修饰符的前缀匹配）会**顺带**吃掉 `/readyz/deepXYZ`
    这类并不存在的路径。契约收窄到 `=`，让「多认了什么」也看得见——宽一点的前缀匹配
    在探针上没有任何收益，却会让一次笔误静默通过。
    """
    return sorted(path for path in probe_paths if declared.get(path) != "=")


class TestGuardGoesRed:
    """★ 把「判据能红」钉死——否则本文件就是又一个永不失败的检查。"""

    def test_guard_goes_red_when_a_registered_probe_has_no_location(self) -> None:
        """给判据一个真实配置里必然没有的探针路径 ⇒ 必须报出来。

        它模拟的正是本条缺陷：**应用注册了端点、配置文件里没有 location**
        （修前 `/readyz/deep` 的真实处境）。
        """
        declared = _nginx_locations(_conf_text())
        missing = _undeclared_probe_paths([_ABSENT_PROBE_PATH], declared)
        assert missing == [_ABSENT_PROBE_PATH], (
            f"判据没能发现一个必然缺失的探针路径 {_ABSENT_PROBE_PATH} ⇒ 它退化成了永不失败的检查"
        )

    def test_guard_goes_red_when_the_modifier_is_not_exact_match(self) -> None:
        """路径在，但只是前缀匹配（无 `=`）⇒ 也要报出来。"""
        text = "location /readyz/deep {\n    proxy_pass http://x;\n}\n"
        missing = _undeclared_probe_paths(["/readyz/deep"], _nginx_locations(text))
        assert missing == ["/readyz/deep"], "前缀匹配被当成了达标 ⇒ 契约被静默放宽"


class TestDiscoverySource:
    """数据源自身的行为——它取空时判据恒真，所以这里必须钉住「不许为空」。"""

    def test_discovery_source_is_not_empty(self) -> None:
        """根级探针路径必须非空，且都不在业务前缀下。

        空集合会让 `test_every_registered_probe_path_has_a_location` 恒真（循环体不执行），
        那正是本文件要避免的失效形态。
        """
        probes = _registered_probe_paths()
        assert len(probes) >= 2, f"根级探针路径只发现 {len(probes)} 条（{sorted(probes)}）——数据源规则疑似失效"
        assert not any(path.startswith(_API_PREFIX) for path in probes), (
            f"数据源把业务接口也当成了探针：{sorted(p for p in probes if p.startswith(_API_PREFIX))}"
        )

    def test_parser_is_discriminating(self) -> None:
        """解析器的正反例：必须同时认出精确/前缀/正则三种写法，且不误认注释行。"""
        text = (
            "# location = /commented-out {  ← 注释里的不算\n"
            "location = /livez {\n    proxy_pass http://x;\n}\n"
            "location /assets/ {\n    root /y;\n}\n"
            "location ~ ^/api/consult/runs/[^/]+/stream$ {\n    proxy_pass http://x;\n}\n"
        )
        assert _nginx_locations(text) == {
            "/livez": "=",
            "/assets/": "",
            "^/api/consult/runs/[^/]+/stream$": "~",
        }


class TestEveryRegisteredProbeIsRoutable:
    """★ 本文件的主判据。"""

    def test_every_registered_probe_path_has_a_location(self) -> None:
        """应用注册的每个根级探针路径，都必须有一条 `location = <路径>`。

        判据**不读**任何硬编码的探针名字：参考集合来自 `campfire.main.app.routes`。
        因此「新增一个探针端点但忘了加 location」会让本条红。
        """
        probes = sorted(_registered_probe_paths())
        # 先自证数据源非空：空集合会让下面的断言恒真（与 TestDiscoverySource 同一理由，
        # 但这里再断言一次是因为本用例是判据本体，失败信息必须指向真因）。
        assert probes, "参考集合为空 ⇒ 本断言恒真，不能作为判据（数据源规则坏了）"

        missing = _undeclared_probe_paths(probes, _nginx_locations(_conf_text()))
        assert missing == [], (
            f"这些探针路径在 {_LOCATIONS_CONF.name} 里没有精确匹配的 location：{missing}\n"
            "缺 location 的后果不是 404，而是落进 SPA 的 `location /`、被 `try_files` 回成\n"
            "`index.html` ⇒ HTTP 200 + text/html（看起来像端点通了）。\n"
            "修法：照 `/readyz` 那条抄一份 `location = <路径>` 反代到 `http://$campfire_api`。"
        )
