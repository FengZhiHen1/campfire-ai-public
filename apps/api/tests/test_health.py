"""健康检查的形状与端点行为。

对应 docs/项目结构设计.md 第 10 节的要求：分别报告各项能力，不用一个全绿接口
表示所有能力安全。因此这里既断言 All-OK 时 200，也断言局部不可用时 503 且
其余能力仍被如实报告。

2026-10-01 起分三个端点，本文件把三者的分工钉住：

- `/livez`：进程活着就 200，不探依赖——依赖挂了重启进程没有意义；
- `/readyz`：面向部署机器判据，覆盖核心业务链（含 Agent 装配）；
- `/health`：面向人排查，与 `/readyz` 同一口径（同一份探针清单）。

`/readyz` 的探针清单由 `main._READINESS_PROBES` 拥有，测试替换整个清单（而不是逐个
替换探针函数）：清单是模块导入期构造的元组、持有对函数的直接引用，逐个 monkeypatch
`main.check_*` 不会影响已经构造好的元组——那样写的测试会在「全部替换了」的错觉下
测到真实探针。
"""

from collections.abc import Awaitable, Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from campfire import main as main_module
from campfire.core.config import Settings, get_settings
from campfire.core.health import ComponentHealth, HealthReport, Status

#: 就绪探针报告的能力名（与 `main._READINESS_PROBES` 的键一致，断言用集合）。
EXPECTED_COMPONENTS = {"auth", "database", "queue", "model", "falkordb", "agent_assembly", "skills"}


def test_report_is_ready_only_when_every_component_is_ok() -> None:
    report = HealthReport((ComponentHealth("database", Status.OK, "连接正常"),))

    assert report.is_ready is True
    assert report.degraded == ()


def test_report_exposes_degraded_components_individually() -> None:
    report = HealthReport(
        (
            ComponentHealth("database", Status.OK, "连接正常"),
            ComponentHealth("model", Status.NOT_CONFIGURED, "未配置 TOKENHUB_API_KEY"),
        )
    )

    assert report.is_ready is False
    assert [item.name for item in report.degraded] == ["model"]
    # 逐层收窄：`as_dict()` 的声明是 `dict[str, object]`（顶层同时放布尔与嵌套字典），
    # 因此要读嵌套值必须先确认形状——顺带钉住这里确实是「按能力名索引的嵌套字典」。
    components = report.as_dict()["components"]
    assert isinstance(components, dict), "components 必须是以能力名为键的字典"
    model = components["model"]
    assert isinstance(model, dict), "每项能力必须给出一份字典"
    assert model["status"] == "not_configured"


def test_report_with_no_components_is_not_ready() -> None:
    """一项能力都没探测时不就绪——空集合上的 `all(...)` 恒为真。

    判别性：去掉 `is_ready` 里的 `bool(self.components)`，本用例失败。

    可达性如实说明：当前唯一装配点（`main.health`）用 `asyncio.gather` 恒传四个
    探针，因此这条分支线上不可触发；本用例不是修当前 bug，而是防将来把组件列表改成
    按配置或插件构造时装配漏传——「没有任何检查」被读成「检查都通过」正是
    AGENTS.md 禁止的闸门形状。
    """
    report = HealthReport(())

    assert report.is_ready is False
    assert report.as_dict()["ready"] is False
    assert report.degraded == ()


def _install_probes(monkeypatch: pytest.MonkeyPatch, *, failing: str | None) -> None:
    """替换整份就绪探针清单为测试替身，避免测试依赖网络与基础设施。

    替换整个元组而不是逐个替换 `main.check_*`：`_READINESS_PROBES` 在导入期就持有
    函数引用，逐个替换不会生效（见文件头说明）。
    """
    attribute_names = {
        "auth": "check_auth_core",
        "database": "check_database",
        "queue": "check_queue",
        "model": "check_model",
        "falkordb": "check_falkordb",
        "agent_assembly": "check_agent_assembly",
        "skills": "check_skill_registry",
    }

    def make(name: str) -> Callable[[Settings], Awaitable[ComponentHealth]]:
        status = Status.UNAVAILABLE if name == failing else Status.OK

        async def probe(_settings: Settings) -> ComponentHealth:
            return ComponentHealth(name, status, "测试替身")

        return probe

    monkeypatch.setattr(
        main_module,
        "_READINESS_PROBES",
        tuple((name, make(name)) for name in attribute_names),
    )
    # 同时把清单里的名字钉住：清单被改名/漏项时本函数立刻报错，而不是静默只测了子集。
    assert {name for name, _ in main_module._READINESS_PROBES} == EXPECTED_COMPONENTS


@pytest.fixture(autouse=True)
def _provide_startup_configuration(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """给 lifespan 提供它要求的配置，让本文件**不依赖宿主机 `.env`**。

    为什么需要它（2026-10-01 实测，这是一条真实的 CI 阻塞）：

    本文件的用例用 `with TestClient(app)` 发请求，而带 `with` 的 `TestClient` **会跑
    `lifespan`**；`lifespan` 调 `init_supertokens(...)`，后者要求
    `SUPERTOKENS_API_KEY`，缺失即抛 `SuperTokensConfigurationError`。

    GitHub Actions 上没有 `.env` 文件（实测：把配好的本机 `.env` 排除后，本文件 6 条
    用例全部 ERROR，**在本次改动之前就已如此**——用会话前的提交 `1c00ce1` 建 worktree
    复现确认过）。也就是说 CI 一直是红的，只是本机的 `.env` 把它盖住了。

    这里给的是假凭据，不会产生任何真实外部调用：本文件的所有探针都被
    `_install_probes` 替换成替身，因此没有请求会发到 SuperTokens core 或模型端点。
    `SUPERTOKENS_API_KEY` 只用于 `init_supertokens` 的装配期校验。

    `get_settings` 是 `lru_cache` 的，故设完环境变量后必须清缓存。
    """
    monkeypatch.setenv("SUPERTOKENS_API_KEY", "health-test-key-not-a-secret")
    monkeypatch.setenv("TOKENHUB_API_KEY", "health-test-key-not-a-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://health:health@127.0.0.1:5432/health_test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_health_returns_200_when_all_capabilities_are_up(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_probes(monkeypatch, failing=None)

    with TestClient(main_module.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert set(body["components"]) == EXPECTED_COMPONENTS
    assert all(item["status"] == "ok" for item in body["components"].values())


def test_health_returns_503_and_still_reports_the_healthy_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_probes(monkeypatch, failing="model")

    with TestClient(main_module.app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["components"]["model"]["status"] == "unavailable"
    # 局部不可用不得掩盖其余能力的真实状态
    assert body["components"]["database"]["status"] == "ok"
    assert body["components"]["queue"]["status"] == "ok"
    assert body["components"]["auth"]["status"] == "ok"


def test_readyz_reports_the_same_set_as_health(monkeypatch: pytest.MonkeyPatch) -> None:
    """`/readyz` 与 `/health` 同一口径——两个路径回答同一个问题，不该有两套结论。"""
    _install_probes(monkeypatch, failing=None)

    with TestClient(main_module.app) as client:
        ready = client.get("/readyz")
        health = client.get("/health")

    assert ready.status_code == 200
    assert ready.json() == health.json()


def test_readyz_is_503_when_agent_runner_is_not_assembled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """核心业务链缺装配时必须 503——这条是这次修掉的「假健康」。

    修复前的真实故障形状（文件头与 `check_agent_assembly` 都记了）：

        GET /health   → 200 OK      （四项依赖都通）
        POST /consult → 503          （运行器没接线）

    部署系统据此认为一个核心咨询功能必然失败的版本已经健康。本用例断言
    `agent_assembly` 是就绪判据的一部分，且它不可用时整体不就绪。

    判别性：把 `("agent_assembly", check_agent_assembly)` 从 `_READINESS_PROBES`
    里去掉，本用例失败（那正是修复前的状态）。
    """
    _install_probes(monkeypatch, failing="agent_assembly")

    with TestClient(main_module.app) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["components"]["agent_assembly"]["status"] == "unavailable"
    # 其余依赖仍如实报告为可用——否则「为什么没就绪」会指向错误的方向
    assert body["components"]["database"]["status"] == "ok"


def test_livez_ignores_every_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """`/livez` 不探任何依赖：依赖全挂时它仍必须 200。

    判别性：把 `/livez` 改成复用 `/readyz`，本用例失败（依赖不可用时会给 503）。
    这一条是「依赖抖动不该触发容器重启」的实现判据——重启进程修不好下游服务。
    """
    for name in EXPECTED_COMPONENTS:
        _install_probes(monkeypatch, failing=name)
        with TestClient(main_module.app) as client:
            response = client.get("/livez")
        assert response.status_code == 200, f"{name} 不可用时 /livez 仍须 200"
        assert response.json() == {"status": "ok"}


def test_agent_assembly_probe_reports_ok_only_when_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    """装配探针直读注入点：未装配报 unavailable，装配后报 ok。

    直接测探针本身（不经过端点），因为它就是「假健康」那条防线的最小单元：
    端点那一侧已经由 `test_readyz_is_503_when_agent_runner_is_not_assembled` 覆盖。
    """
    import asyncio

    from campfire.surfaces.consult import assembly as consult_assembly

    monkeypatch.setattr(consult_assembly, "_runner_factory", None)
    unwired = asyncio.run(main_module.check_agent_assembly(get_settings_for_probe()))
    assert unwired.status is Status.UNAVAILABLE
    assert "未装配" in unwired.detail

    monkeypatch.setattr(consult_assembly, "_runner_factory", lambda _settings: object())
    wired = asyncio.run(main_module.check_agent_assembly(get_settings_for_probe()))
    assert wired.status is Status.OK

    monkeypatch.setattr(consult_assembly, "_runner_factory", None)


def test_falkordb_probe_reports_unavailable_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """图库不可达时探针必须**返回**不可用，而不是抛异常。

    这条锁的是一个真实缺陷（2026-10-01 在容器里实测到）：`FalkorDB(...)` 的构造函数
    **本身就发网络 I/O**，图库挂掉时它在构造期就抛 `ConnectionError`。第一版把构造写在
    `try` 之外，于是 `/readyz` 在图库挂掉时回 **500**（未捕获异常）而不是
    「503 且 falkordb 项不可用」——恰好毁掉探针存在的意义：让健康检查如实报告，
    而不是把自己炸掉。

    判别性：把 `FalkorDB(...)` 的构造移回 `try` 之外，本用例失败（抛异常而非返回结论）。
    """
    import asyncio

    def exploding_falkordb(*_args: object, **_kwargs: object) -> object:
        raise ConnectionRefusedError("图库不可达（测试替身）")

    monkeypatch.setattr(main_module, "FalkorDB", exploding_falkordb)

    result = asyncio.run(main_module.check_falkordb(get_settings_for_probe()))

    assert result.status is Status.UNAVAILABLE
    assert result.name == "falkordb"
    assert "ConnectionRefusedError" in result.detail


def test_readiness_endpoint_is_503_not_500_when_a_probe_explodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任何探针炸掉时端点都必须是 503（可判读的结论），而不是 500。

    部署系统只看状态码：503 表示「暂时不可服务，别给流量」，500 表示「服务自己坏了」。
    把「依赖不可达」报成 500 会让编排层与告警误判方向。

    这里覆盖 `falkordb` 这一项（它是实际踩到的那个），但断言的是端点的整体行为。
    """
    _install_probes(monkeypatch, failing="falkordb")

    with TestClient(main_module.app) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["components"]["falkordb"]["status"] == "unavailable"


def get_settings_for_probe() -> Settings:
    """探针只读 `Settings` 的少数字段；给一份默认配置，不依赖宿主机 .env 的取值。"""
    return Settings(_env_file=None)  # type: ignore[call-arg]  # `_env_file` 是 BaseSettings 的公开参数，合成签名里没有它
