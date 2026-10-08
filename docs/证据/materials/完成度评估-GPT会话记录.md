只读检查后的结论很明确：**当前分支的业务实现已经接近“可部署候选”，但还没有达到正式部署标准。** 这不是因为 profile、case、前端之类还没做完——这些其实已经比旧文档记录先进很多——而是剩下几个集中在“生产装配与运维闭环”的关键阻塞。

### 当前实际完成度

我按源码重新核对后，下面这些已经真实落地，旧 `TODO` / `服务器选型事实基线` 中不少描述已经过期：

| 项目 | 当前实际状态 |
|---|---|
| React H5 | 已有完整 Vite/React 工程和 build/test/lint/typecheck |
| 主要页面 | 首页、咨询列表、对话、应急、档案、案例、设置、记忆、指南均已接真实页面 |
| Profile | 已有 models / repository / service / routes / consumer / purge |
| Case | 已有 case schema、ingestion、检索、路由和迁移 |
| 数据库迁移 | SDK 会话表、`campfire_session`、profile、case、墓碑、六值 origin 等已出现 |
| Agent skills | 已有 `daily-consulting`、`emergency-consulting`、`onboarding`、`profile-curation` 四个 skill |
| Agent 产品工具 | 当前注册表里 **10 个已经齐全** |
| Question Card | 已实现事件与 `ask_user` |
| Action Card | 已实现 |
| reasoning_delta | 已实现 |
| Worker | Taskiq、pending write、消费与兜底扫描已经有实际实现 |
| 认证 | SuperTokens 已进入实际 HTTP 装配 |
| 前后端路由 | 已不再是“只有 `/health`”的骨架状态 |

所以，**不应该再根据旧文档得出“Campfire-AI 业务实现刚开始”的判断。**

但目前有几个阻塞，其中第一个是绝对 P0。

| 级别 | 问题 | 为什么阻塞部署 |
|---|---|---|
| **P0** | AgentRunner 没有生产装配 | 核心咨询功能必然 503 |
| **P0** | CitationIndex 没有持久化实现 | AgentRunner 本身无法完整构造 |
| **P0** | 没有生产 Docker/Compose/Nginx | 无法进行可重复、可回滚的服务器部署 |
| **P1** | `/health` 会产生假健康 | Agent 不可用时仍可能返回 200 |
| **P1** | CI 与实际工程严重脱节 | 前端完全不进 CI，集成测试实际被 skip |
| **P1** | CD 被明确停用 | 当前不存在发布链路 |
| **P1** | 备份/恢复/回滚体系不存在 | 数据型产品无法按生产要求上线 |
| **P1** | 可观测性不足 | Worker、图库、业务链故障不易发现 |
| 发布闸门 | EVID-A～D/F | 不影响技术 staging，但影响面向真实使用者 |

其中最重要的是 Agent 装配。

当前 `surfaces/consult/assembly.py` 自己明确写着：

```python
_runner_factory: Callable[[Settings], AgentRunner] | None = None
```

并且：

```python
def get_runner(settings: Settings) -> AgentRunner:
    if _runner_factory is None:
        raise ConsultAssemblyError(
            "运行器尚未装配：本进程没有可用的 AgentRunner"
        )
```

我重新全仓搜索了：

```text
set_runner_factory(...)
```

**没有生产调用点。**

`main.py` 也明确承认这个状态：

```python
if not runner_is_wired():
    logger.warning(
        "咨询面运行器尚未装配：发消息端点将回 503"
    )
```

这不是测试覆盖问题，而是**当前静态代码就确定存在的运行时行为**。

而且缺的不只是最后一行 `set_runner_factory()`。

一个 `AgentRunner` 构造需要：

```python
AgentRunner(
    binding=...,
    tools=...,
    skills=...,
    citations=...,
    sessions=...,
)
```

其中现有代码已经分别具备大量零件：

```text
ModelGateway
ToolPool
10 个产品工具
4 个 skills
build_skill_tool()
build_read_skill_resource_tool()
build_ask_user_tool()
build_sqlalchemy_session()
```

但是这些零件目前**没有生产组合根**。

尤其 `CitationIndex`：

```python
class CitationIndex(Protocol):
    ...
```

全仓只有协议、Recorder 和测试替身，**没有持久化实现**。`assembly.py` 的注释也明确承认这一点。

所以现在最准确的状态是：

```text
Agent 基座       ✅
模型 Gateway     ✅
Skill runtime    ✅
Tool system      ✅
产品工具          ✅
会话存储          ✅
HTTP/SSE         ✅
前端消费          ✅

             ↓

生产 Composition Root   ❌
CitationIndex 实现       ❌

             ↓

完整咨询链              ❌
```

这是正式部署之前首先要修的。

---

另一个比较隐蔽但严重的问题是 `/health`。

目前 `/health` 只检查：

```python
check_auth_core(settings)
check_database(settings)
check_model(settings)
check_queue(settings)
```

也就是：

```text
SuperTokens
PostgreSQL
TokenHub
Redis
```

但没有检查：

```text
AgentRunner 是否完成装配
Skill registry 是否可加载
FalkorDB 是否可用
CitationIndex 是否可用
```

于是存在这种完全可能的生产状态：

```text
GET /health
→ 200 OK

POST /consult/...
→ 503 runner not wired
```

这对 Docker healthcheck、Nginx upstream、CD 发布验证来说都是危险的，因为**部署系统会认为一个实际上不能提供核心业务的版本已经健康**。

部署设计时我建议明确区分：

```text
/livez
    进程活着即可

/readyz
    DB
    Redis
    SuperTokens
    FalkorDB
    TokenHub
    Skill registry
    AgentRunner composition
    必要迁移状态
    全部达到可服务状态

/health
    可保留为组件诊断
```

至少生产 readiness 必须包含 Agent 装配。

---

基础设施方面则更加直接。

目前：

```text
infrastructure/
├── docker/
└── nginx/
```

仍然是空的。

没有当前实现对应的：

```text
Dockerfile.api
Dockerfile.web
compose.prod.yml
nginx.conf
deploy script
migration release step
rollback script
```

现存 Dockerfile 全部位于：

```text
archive/
```

按照项目自己的规则不能拿来作为现行部署依据。

`.github/workflows/deploy.yml` 也仍然是：

```yaml
if: false
```

也就是说现在没有 CD。

所以即便我今天把 AgentRunner 接好，也仍然只能说：

> 应用源码具备发布候选条件。

还不能说：

> 仓库具备生产部署条件。

---

CI 也需要在部署前修正。

当前 `apps/web` 已经有：

```text
React 19
Vite
Vitest
oxlint
TypeScript
完整 build script
```

但 GitHub CI 仍然写着：

> apps/web 目前只有目录占位

并且整个 frontend job 根本没有启用。

因此现在完全可能发生：

```text
前端无法编译
      ↓
GitHub CI 仍然全绿
      ↓
master 被认为可发布
```

这显然不能作为 CD 的发布闸门。

另外后端 CI 现在没有 PostgreSQL service / DATABASE_URL，所以带 `integration` marker 的测试不会构成 GitHub 合并门禁。你这次要求“不运行测试”，所以我**没有验证现在有多少测试被 skip，也没有验证当前测试是否通过**；这里只是从 workflow 静态代码确认它没有为集成环境提供数据库。

---

运维侧也还没有生产闭环。

我静态搜索当前源码，没有找到真正的 backup 实现；同样没有完整的 metrics/监控输出。目前主要还是日志。

对 Campfire-AI 这种同时保存：

```text
PostgreSQL
├── 账号业务数据
├── 会话
├── 档案
├── RAG 数据
└── 删除/审计相关状态

FalkorDB
└── Graphiti 长期记忆

Redis
└── 队列与短期状态
```

的应用而言，正式部署前至少要定义：

```text
PostgreSQL 定时备份
FalkorDB 持久化 + 备份
恢复演练
保留周期
发布前 DB snapshot
Alembic 前向迁移
代码回滚 + 数据库兼容策略
```

否则“能启动”不等于“可生产运行”。

---

### 因此，我建议重新定义现在的位置

当前分支已经不再是：

```text
开发骨架
```

而应该视为：

```text
业务实现基本成形
        ↓
生产装配阶段   ← 现在在这里
        ↓
Staging
        ↓
发布验收
        ↓
试点 Production
```

现在最合理的顺序也因此发生了一点变化。

我们**不应该直接开始写 Dockerfile**，而应该先完成一个很小但关键的“应用生产装配”阶段：

```text
① 实现 CitationIndex
        ↓
② 新建 production Agent composition root
        ↓
③ ModelGateway
   + SkillRegistry
   + ToolPool
   + CitationIndex
   + SQLAlchemySession
   → AgentRunner
        ↓
④ main.py 注入 set_runner_factory(...)
        ↓
⑤ lifecycle 正确关闭 ModelGateway / DB / Redis / Falkor
        ↓
⑥ readiness 覆盖核心链路
```

做到这里之后，Campfire-AI 才真正成为一个**完整可启动的应用**。

然后再进入我前面说的部署设计：

```text
Dockerfile
→ production Compose
→ Nginx
→ TLS
→ secrets
→ Alembic release
→ backup
→ health/readiness
→ GitHub CI
→ GHCR
→ CD
→ rollback
```

最后还有一个不同层面的限制：仓库自己的发布规则把 `EVID-A`～`EVID-D` 等列为**面向真实使用者之前的证据闸门**。这不会阻止我们把系统部署到香港服务器做 staging、评委演示或使用虚构/不可识别数据测试；但如果后面要让真实家庭输入真实敏感资料，就需要再逐项处理这些闸门。

**所以我的判断是：现在不能直接判定“达到部署标准”，但已经达到“可以正式进入生产化改造”的阶段。最大的代码阻塞不是业务页面，而是 Agent 的最后生产装配。**

我建议我们接下来先把这个 P0 闭合，再开始生产部署设计；否则会出现一种很糟糕的情况：Docker、Nginx、TLS、CD 全做好了，部署出来的版本却在核心咨询端点稳定返回 503。