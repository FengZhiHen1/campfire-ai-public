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

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable, Iterator

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from campfire import main as main_module
from campfire.core.config import EMBEDDING_DIM, Settings, get_settings
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
    """给 lifespan 提供它要求的配置，让本文件不依赖宿主机 `.env`。

    为什么需要它（2026-10-01 实测，这是一条真实的 CI 阻塞）：

    本文件的用例用 `with TestClient(app)` 发请求，而带 `with` 的 `TestClient` **会跑
    `lifespan`**；`lifespan` 调 `init_supertokens(...)`，后者要求
    `SUPERTOKENS_API_KEY`，缺失即抛 `SuperTokensConfigurationError`。

    GitHub Actions 上没有 `.env` 文件（实测：把配好的本机 `.env` 排除后，本文件 6 条
    用例全部 ERROR，在本次改动之前就已如此——用会话前的提交 `1c00ce1` 建 worktree
    复现确认过）。也就是说 CI 一直是红的，只是本机的 `.env` 把它盖住了。

    这里给的是假凭据，不会产生任何真实外部调用：本文件的所有探针都被
    `_install_probes` 替换成替身，因此没有请求会发到 SuperTokens core 或模型端点。
    `SUPERTOKENS_API_KEY` 只用于 `init_supertokens` 的装配期校验。

    `get_settings` 是 `lru_cache` 的，故设完环境变量后必须清缓存。
    """
    from campfire.core import cache, db
    from campfire.modules.memory import graph

    # TestClient 的 lifespan 在独立循环运行，不能接管异步集成用例的会话级连接。
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    monkeypatch.setattr(cache, "_cache", None)
    monkeypatch.setattr(graph, "_shared_graph", None)
    monkeypatch.setattr(graph, "_shared_graph_origin", None)
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
    """图库不可达时探针必须返回不可用，而不是抛异常。

    这条锁的是一个真实缺陷（2026-10-01 在容器里实测到）：`FalkorDB(...)` 的构造函数
    本身就发网络 I/O，图库挂掉时它在构造期就抛 `ConnectionError`。第一版把构造写在
    `try` 之外，于是 `/readyz` 在图库挂掉时回 500（未捕获异常）而不是
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
    """探针只读 `Settings` 的少数字段；给一份默认配置，不依赖宿主机 .env 的取值。

    三个可拆分的端点/凭据显式钉成未配置（2026-10-29 全量基线实测）：只关 `.env` 文件
    挡不住**环境变量**——`.env` 被 `set -a; source .env` 导出（或用空值导出）之后，
    `EMBEDDING_*` / `MEMORY_LLM_*` 仍在进程里，而 pydantic-settings 的环境变量优先级
    高于 `_env_file`，于是「默认值」这条判据会读到别人的配置。
    """
    return Settings(  # type: ignore[call-arg]  # `_env_file` 是 BaseSettings 的公开参数，合成签名里没有它
        _env_file=None,
        embedding_base_url="",
        embedding_api_key=None,
        memory_llm_base_url="",
        memory_llm_api_key=None,
    )


# ---------------------------------------------------------------------------
# 深度就绪探针：`/readyz/deep`（T19）
#
# 这一组把本包的核心决定钉住：**embedding 探测只在按需端点里，绝不进周期清单**。
# 加它的动机是一个真实发生过的缺陷形态——`/readyz` 的 `model` 项只探 chat 端点
# （`GET /models`），而 chat 与 embedding 是两条独立链路，于是
# 「健康检查全绿而记忆写入整体不可用」探不到（Graphiti embedder 漏传
# `encoding_format` ⇒ TokenHub 400001 ⇒ `add_episode` 必失败）。
# ---------------------------------------------------------------------------

#: 深度探针比 readiness 多出来的那一项（与 `main._EMBEDDING_PROBE` 的键一致）。
DEEP_ONLY_COMPONENT = "embedding"


def test_embedding_probe_is_not_in_the_readiness_list() -> None:
    """**承重用例**：`embedding` 不在 readiness 清单里，只在深度清单里。

    这是本包最容易被破坏的东西，因此分两层钉：

    1. **清单层**（`_READINESS_PROBES`）——`/readyz` 与 `/health` 共用它，
       所以「不在清单里」就等于「两个端点的组件集合都不含它」；
    2. **深度层**——`_deep_probes()` 必须是 readiness 的**超集且只多它一项**。

    判别性（实测，见报告第 5 节）：把 `("embedding", check_embedding)` 挪进
    `_READINESS_PROBES`（并把它从 `_EMBEDDING_PROBE` 处删掉），本用例**必然红**
    ——那时第一个断言就失败。这正是判据要抓的那次错误改动。

    为什么值得一条专门的用例：把真实嵌入调用放进周期清单的代价不是风格问题——
    生产 healthcheck 每 15 秒一次，那约等于 **5760 次/天**的真实嵌入请求。
    """
    readiness_names = {name for name, _ in main_module._READINESS_PROBES}

    assert DEEP_ONLY_COMPONENT not in readiness_names, (
        f"{DEEP_ONLY_COMPONENT} 混进了 readiness 清单：/readyz 与 /health 都会真的调用嵌入端点，"
        "而生产 healthcheck 每 15 秒跑一次（约 5760 次/天，有配额成本）。"
        "真实嵌入探测只应存在于 /readyz/deep。"
    )
    assert DEEP_ONLY_COMPONENT not in EXPECTED_COMPONENTS, "测试常量与 readiness 清单口径不一致"

    deep_names = {name for name, _ in main_module._deep_probes()}
    assert deep_names == readiness_names | {DEEP_ONLY_COMPONENT}, (
        f"深度清单不是「readiness + {DEEP_ONLY_COMPONENT}」：实际 {sorted(deep_names)}"
    )


def test_deep_probes_follow_the_readiness_list_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """深度清单按调用时展开，不持有导入期快照。

    为什么钉这条：若 `_deep_probes()` 在导入期算成一个常量，readiness 清单后来被
    替换（测试会这么做，将来按配置构造也会）时 `/readyz/deep` 就会探一个**过时的集合**
    ——表现为「少探了一项」而没有任何症状。`test_health.py` 的文件头正是为同一个坑写的
    （逐个 monkeypatch `main.check_*` 不影响已经构造好的元组）。
    """
    _install_probes(monkeypatch, failing=None)

    deep_names = {name for name, _ in main_module._deep_probes()}

    assert deep_names == EXPECTED_COMPONENTS | {DEEP_ONLY_COMPONENT}


def _install_deep_probe(monkeypatch: pytest.MonkeyPatch, *, failing: bool) -> None:
    """把深度端点专属的那一项换成替身（避免真实嵌入调用与配额消耗）。"""

    async def probe(_settings: Settings) -> ComponentHealth:
        status = Status.UNAVAILABLE if failing else Status.OK
        return ComponentHealth(DEEP_ONLY_COMPONENT, status, "测试替身")

    monkeypatch.setattr(main_module, "_EMBEDDING_PROBE", (DEEP_ONLY_COMPONENT, probe))


def test_readyz_does_not_expose_the_embedding_component(monkeypatch: pytest.MonkeyPatch) -> None:
    """端点层：`/readyz` 的响应里**没有** `embedding` 项（即使深度探针被替换过）。

    这一层与清单层分开断言，是因为两件事的失效方式不同：清单被改坏时这里也红，
    而「端点自己把深度项并进来」时只有这里红。
    """
    _install_probes(monkeypatch, failing=None)
    _install_deep_probe(monkeypatch, failing=False)

    with TestClient(main_module.app) as client:
        ready = client.get("/readyz")
        health = client.get("/health")

    assert ready.status_code == 200
    assert set(ready.json()["components"]) == EXPECTED_COMPONENTS
    assert DEEP_ONLY_COMPONENT not in ready.json()["components"]
    # `/health` 与 `/readyz` 同一口径：这一项同样不得出现在它里面
    assert DEEP_ONLY_COMPONENT not in health.json()["components"]
    assert ready.json() == health.json()


def test_readyz_deep_exposes_the_embedding_component(monkeypatch: pytest.MonkeyPatch) -> None:
    """端点层：`/readyz/deep` 的组件集合 = `/readyz` 的七项 + `embedding`，且全 ok 才 200。"""
    _install_probes(monkeypatch, failing=None)
    _install_deep_probe(monkeypatch, failing=False)

    with TestClient(main_module.app) as client:
        response = client.get("/readyz/deep")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert set(body["components"]) == EXPECTED_COMPONENTS | {DEEP_ONLY_COMPONENT}
    assert body["components"][DEEP_ONLY_COMPONENT]["status"] == "ok"


def test_readyz_deep_is_503_when_the_embedding_probe_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """嵌入探测失败时深度端点必须 503——否则它与 `/readyz` 就没有区别了。

    判别性：把 `_EMBEDDING_PROBE` 从 `_deep_probes()` 里去掉，本用例失败
    （那时 `embedding` 项不存在，`body["components"][...]` 直接 KeyError）。
    """
    _install_probes(monkeypatch, failing=None)
    _install_deep_probe(monkeypatch, failing=True)

    with TestClient(main_module.app) as client:
        response = client.get("/readyz/deep")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["components"][DEEP_ONLY_COMPONENT]["status"] == "unavailable"
    # 其余七项仍如实报告为可用——否则「为什么没就绪」会指向错误的方向
    assert body["components"]["database"]["status"] == "ok"
    assert body["components"]["model"]["status"] == "ok"


def test_deep_readiness_endpoint_is_reachable_without_a_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """`/readyz/deep` 未登录可达（与 `/readyz`、`/health` 同属运维探针端点）。

    依据 `AC-01`：「唯一例外是**运维探针端点**」。它与 `/readyz` 是同类——面向发布验收与
    人工诊断的机器判据，Nginx 上游检查与运维都不持会话。它不构成业务能力，且只回报
    组件状态与异常类型，不复述连接串、凭据或内部拓扑。

    本用例不装认证桩：请求一路走到端点，证明中间没有任何会话依赖。
    """
    _install_probes(monkeypatch, failing=None)
    _install_deep_probe(monkeypatch, failing=False)

    with TestClient(main_module.app) as client:
        response = client.get("/readyz/deep")

    assert response.status_code == 200, "深度探针端点被鉴权挡住了——它与 /readyz 必须同类"


# ---------------------------------------------------------------------------
# 嵌入探针本身：真的发一次请求、断言维度（**全部走假传输，不消耗配额**）
#
# 假传输按 TokenHub 的真实规则行事：**只接受 `encoding_format="float"`**，其余回 400。
# 那不是为了让测试好看，而是把「本轮那个真实缺陷」变成可复现的判据——SDK 注入 `base64`
# 时真实端点正是这样拒的（实测 400001）。因此下面「错形态 ⇒ 探针红」的用例不是模拟，
# 是同一因果链在假传输上的重演。
# ---------------------------------------------------------------------------


def _recording_transport(
    bodies: list[dict[str, object]],
    *,
    dim: int,
    status: int = 200,
) -> httpx2.MockTransport:
    """假传输：记录请求体，按 TokenHub 的规则应答（只收 `encoding_format="float"`）。

    `status` 非 200 时直接回那个状态码，用来覆盖「供应商拒了」的分支。
    """

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if status != 200:
            return httpx2.Response(status, json={"error": {"code": "400001", "message": "rejected"}})
        if body.get("encoding_format") != "float":
            # TokenHub 的真实行为（实测 400001）：只接受 float。**必须在假传输里复刻**，
            # 否则「错形态探针红」这条用例会因为假传输太宽容而变成假绿。
            return httpx2.Response(
                400,
                json={
                    "error": {
                        "code": "400001",
                        "message": "The request is invalid: encoding_format only supports float",
                    }
                },
            )
        raw = body.get("input")
        count = len(raw) if isinstance(raw, list) else 1
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "model": "kinfra-text-embedding-4b",
                "data": [{"object": "embedding", "index": i, "embedding": [0.5] * dim} for i in range(count)],
            },
        )

    return httpx2.MockTransport(handler)


def _install_embedder_with_recording_transport(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dim: int = EMBEDDING_DIM,
    status: int = 200,
    break_encoding_format: bool = False,
) -> list[dict[str, object]]:
    """把探针用的嵌入器挂到假传输上，返回请求体记录列表。

    **不替换探针的构造**：走的是真实的 `build_memory_embedder`（因此 `TokenHubEmbedder`、
    `encoding_format="float"`、`max_retries=0` 全部是生产那一份），只在它返回之后换掉最底层
    传输——要断言的正是「真的发了什么」，只能在传输层截获。

    `break_encoding_format=True` 复现**错形态**：把生产工厂用的嵌入器**类**换回上游的
    `OpenAIEmbedder`（`build_memory_embedder` 照常被调用）——那正是 T12 修掉缺陷之前的形状，
    也正是 `build_memory_graph` 若被改回上游实现就长成的样子。

    为什么换的是**类**而不是清空 `additional_kwargs`，也不是事后改字段（**两条实测教训，2026-10-05**）：

    - 清空 `additional_kwargs` 无效：`TokenHubEmbedder.create()` 把 `encoding_format="float"`
      **写死在调用里**，对它毫无影响，请求体仍是 `float` ⇒ 那种消融会**假绿**
      （本用例第一版就这么写，实测失败暴露了它）。对比：
      `modules/library/embedding.py` 的 `OpenAIEmbedding` 才是靠 `additional_kwargs` 传的，
      对那种形状清空它才有效。
    - 事后替换 `holder.embedder` 会抛 `FrozenInstanceError`：`MemoryEmbedder` 是
      `frozen=True` 的 dataclass（实测），字段不可重绑。这恰好是它的设计意图——
      持有者一旦拿到就不能被换掉。

    ⇒ 唯一忠实的复现方式是让**生产那条构造路径自己产出错形态**：替换
    `build_memory_embedder` 内部使用的 embedder 类。两组之间因此只差这一个类。
    """
    from graphiti_core.embedder.openai import OpenAIEmbedder

    import campfire.modules.memory.graph as memory_graph

    real_factory = main_module.build_memory_embedder
    bodies: list[dict[str, object]] = []

    def patched(settings: Settings, **kwargs: object) -> object:
        # 只换工厂用的那个类，工厂自身的代码逐字不动 ⇒ 两组之间唯一差异就是这个类。
        if break_encoding_format:
            monkeypatch.setattr(memory_graph, "TokenHubEmbedder", OpenAIEmbedder)
        holder = real_factory(settings, **kwargs)  # type: ignore[arg-type]  # 原样转交，签名由真实工厂保证
        # `AsyncOpenAI` 把注入的 httpx2 客户端放在 `_client` 上（实测），换掉它的传输。
        holder.client._client._transport = _recording_transport(bodies, dim=dim, status=status)  # type: ignore[attr-defined]  # 测试要截获真实请求体，只能从传输层下手（test_memory_graph 同做法）
        return holder

    monkeypatch.setattr(main_module, "build_memory_embedder", patched)
    return bodies


def _probe_settings() -> Settings:
    """探针用的配置：显式给假凭据与固定 base_url，不依赖宿主机 .env。

    嵌入侧的两个字段必须一起钉住：`EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` 一旦
    被导出成环境变量（哪怕是空串），就会压过 `_env_file=None` 与字段默认值，
    探针于是去建一个连凭据都不合法的客户端——那是「环境串线」，不是探针缺陷
    （2026-10-29 全量基线实测：本文件 6 条嵌入探针用例就是这么红的）。
    """
    return Settings(  # type: ignore[call-arg]  # `_env_file` 不在合成签名里
        _env_file=None,
        tokenhub_api_key=SecretStr("health-test-key-not-a-secret"),
        tokenhub_base_url="https://tokenhub.example/v1",
        embedding_model_name="kinfra-text-embedding-4b",
        embedding_base_url="",
        embedding_api_key=None,
        memory_llm_base_url="",
        memory_llm_api_key=None,
    )


def _settings_without_credentials() -> Settings:
    """一份**没有**凭据的配置（显式 `None` 覆盖环境变量，见对应用例的说明）。"""
    return Settings(  # type: ignore[call-arg]  # `_env_file` 不在合成签名里
        _env_file=None,
        tokenhub_api_key=None,
        # 嵌入与记忆都可以单独配凭据（见 core/config）；「没有凭据」这条判据
        # 必须把三个入口一起清空，否则本机 .env 一配就再也测不出这个分支。
        embedding_api_key=None,
        memory_llm_api_key=None,
    )


def test_embedding_probe_sends_exactly_one_short_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """探针只发 **1 次**极短输入的请求，且带 `encoding_format="float"`。

    「只发 1 次」是配额纪律（任务包要求），因此它是断言而不是注释：多探几次不会让
    结论更准，只是成倍花钱。输入必须是固定字面量——不得发送任何使用者数据。
    """
    bodies = _install_embedder_with_recording_transport(monkeypatch)

    result = asyncio.run(main_module.check_embedding(_probe_settings()))

    assert result.name == "embedding"
    assert len(bodies) == 1, f"探针发了 {len(bodies)} 次请求，必须恰好 1 次（配额纪律）"
    body = bodies[0]
    assert body["encoding_format"] == "float", "探针的请求体必须是 float（否则真实端点会拒 400001）"
    assert body["model"] == "kinfra-text-embedding-4b"
    assert body["input"] == main_module._EMBEDDING_PROBE_INPUT, "探针必须发那条固定字面量，不得发送使用者数据"
    assert len(main_module._EMBEDDING_PROBE_INPUT) < 64, "探针输入应当是极短的（配额纪律）"


def test_embedding_probe_reports_ok_with_the_configured_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    """维度与常量一致时探针报 ok，且 detail 里带上实际维度值（供运维直接读）。"""
    _install_embedder_with_recording_transport(monkeypatch, dim=EMBEDDING_DIM)

    result = asyncio.run(main_module.check_embedding(_probe_settings()))

    assert result.status is Status.OK
    assert str(EMBEDDING_DIM) in result.detail, "detail 应带上实际维度值，运维不必再数一遍"
    assert EMBEDDING_DIM == 2560, "维度常量变了：请先核实供应商侧的向量维度并同步设计文档"


def test_embedding_probe_is_unavailable_when_dimension_disagrees(monkeypatch: pytest.MonkeyPatch) -> None:
    """返回维度与常量不一致时探针报 unavailable（并把两个数字都写进 detail）。

    判别性：去掉 `check_embedding` 里的维度断言，本用例失败（那时它会报 ok）。

    Note:
        这里用**更短**的向量（2560→2048）而不是更长的：更长的会被 `TokenHubEmbedder`
        的既有截断掩掉而探针仍绿——那条边界实测确认过，写在 `check_embedding` 的
        docstring 与报告的证据边界一节。用更短的那个才真的在测断言。
    """
    _install_embedder_with_recording_transport(monkeypatch, dim=EMBEDDING_DIM - 512)

    result = asyncio.run(main_module.check_embedding(_probe_settings()))

    assert result.status is Status.UNAVAILABLE
    assert str(EMBEDDING_DIM - 512) in result.detail
    assert str(EMBEDDING_DIM) in result.detail


def test_embedding_probe_catches_the_encoding_format_defect(monkeypatch: pytest.MonkeyPatch) -> None:
    """**承重用例**：embedder 漏传 `encoding_format` 时探针必须报 unavailable。

    这条钉的就是本包存在的理由。缺陷形态（T12 修掉的那个，P1）：
    上游 `OpenAIEmbedder` 只传 `input` + `model` ⇒ SDK 在请求体层面注入
    `encoding_format="base64"` ⇒ TokenHub 只接受 `float` ⇒ **400001** ⇒
    `add_episode` 必失败 ⇒ 记忆写入路径整体不可用。而 `/readyz` 的 `model` 项
    只探 chat 端点（`GET /models`），**抓不到参数级缺陷**。

    判别性（消融）：把 `_install_embedder_with_recording_transport` 的
    `break_encoding_format=True` 去掉，请求体回到 `float`，本用例失败——即
    「本用例确实在测那个开关，而不是恒红」。
    """
    bodies = _install_embedder_with_recording_transport(monkeypatch, break_encoding_format=True)

    result = asyncio.run(main_module.check_embedding(_probe_settings()))

    assert bodies[0]["encoding_format"] == "base64", "错形态未生效，本用例失去对象（假传输必须按 TokenHub 规则拒它）"
    assert result.status is Status.UNAVAILABLE, (
        "embedder 漏传 encoding_format（SDK 注入 base64、TokenHub 拒 400001）时探针仍报 ok——"
        "这正是本包要消灭的『探针绿而记忆写入全坏』"
    )
    assert result.name == "embedding"


def test_embedding_probe_surfaces_provider_status_without_echoing_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """供应商拒付时只报状态码与异常类型名，**不复述响应体**（AGENTS.md 安全条款）。

    响应体可能含连接串、凭据片段或内部拓扑；探针的 detail 会进日志与告警，
    因此它只能带「可操作而不敏感」的信息。
    """
    _install_embedder_with_recording_transport(monkeypatch, status=400)

    result = asyncio.run(main_module.check_embedding(_probe_settings()))

    assert result.status is Status.UNAVAILABLE
    assert "400" in result.detail
    assert "BadRequestError" in result.detail
    # 供应商响应体的内容一个字都不该出现
    assert "400001" not in result.detail
    assert "encoding_format only supports float" not in result.detail


def test_embedding_probe_reports_not_configured_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺凭据时报 not_configured（配置问题），而不是把它说成端点不可达。

    **显式传 `tokenhub_api_key=None`**（而不是只靠 `_env_file=None`）：本文件的 autouse
    夹具会给进程设一个假 key，而 pydantic-settings 里环境变量优先于默认值 ⇒ 不显式覆盖
    的话这里拿到的仍是假 key，于是探针会**真的发一次网络请求**（实测：拿到 401
    `AuthenticationError`，被报成 unavailable）。那样既不是本用例要测的分支，
    也让用例依赖网络。显式 `None` 在 pydantic-settings 里是**有效覆盖**（实测）。
    """
    result = asyncio.run(main_module.check_embedding(_settings_without_credentials()))

    assert result.name == "embedding"
    assert result.status is Status.NOT_CONFIGURED
    # 与 `check_model` 同形：缺凭据的文案不得复述任何凭据值
    assert "TOKENHUB_API_KEY" in result.detail


def test_embedding_probe_explains_a_transport_failure_as_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """传输类失败报「不可达」并带上异常类型；其余异常不得被描述成网络问题。

    这里用「构造期抛 APIConnectionError」的替身覆盖不可达分支（真实网络失败要等超时，
    不适合放进单测）。判别性：把 `check_embedding` 的 `APIConnectionError` 分支删掉，
    本用例会落到兜底的「探针自身异常」文案上而失败。
    """
    import openai

    import campfire.modules.memory.graph as memory_graph
    from campfire.modules.memory.graph import TokenHubEmbedder

    class _ExplodingEmbedder(TokenHubEmbedder):
        """真实 embedder 的子类，只把发请求那一步换成抛连接错误。

        继承而不是鸭子类型：这样它与生产 embedder 同形（其余方法、config、client 全沿用），
        差异只有「网络那一跳失败了」这一件事。
        """

        async def create(
            self,
            input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]],
        ) -> list[float]:
            raise openai.APIConnectionError(request=httpx2.Request("POST", "https://tokenhub.example/v1/embeddings"))

    real_factory = main_module.build_memory_embedder

    def patched(settings: Settings, **kwargs: object) -> object:
        monkeypatch.setattr(memory_graph, "TokenHubEmbedder", _ExplodingEmbedder)
        return real_factory(settings, **kwargs)  # type: ignore[arg-type]  # 原样转交

    monkeypatch.setattr(main_module, "build_memory_embedder", patched)

    result = asyncio.run(main_module.check_embedding(_probe_settings()))

    assert result.status is Status.UNAVAILABLE
    assert "不可达" in result.detail
    assert "APIConnectionError" in result.detail
