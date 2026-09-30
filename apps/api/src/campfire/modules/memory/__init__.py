"""通用记忆：写入与读取、时间演变与失效判定。

职责：导出本模块的用例、装配入口与异常层次。
边界：只做转出，不在这里实现业务逻辑。
参考：见 docs/项目结构设计.md 与 docs/TODO.md `TECH-05`。
"""

from campfire.modules.memory.deletion import (
    DeletionResult,
    correct_episode,
    delete_episode,
)
from campfire.modules.memory.derived import (
    EMERGENCY_MEMORY_CHARS,
    EMERGENCY_MEMORY_LIMIT,
    DerivedFact,
    EmergencyMemory,
    read_emergency_facts,
)
from campfire.modules.memory.errors import (
    MemoryConfigurationError,
    MemoryDataError,
    MemoryModuleError,
    MemoryUnavailableError,
)
from campfire.modules.memory.graph import MemoryGraph, build_memory_graph
from campfire.modules.memory.identity import (
    AccountId,
    AccountIdError,
    EpisodeUuid,
    PendingId,
    derive_episode_uuid,
    to_account_id,
)
from campfire.modules.memory.ledger import (
    DELETED_KEYS_LIMIT,
    DeletionOutcome,
    DeletionRecord,
    deleted_episode_keys,
    record_deletion,
)
from campfire.modules.memory.purge import MemoryAccountPurger, delete_ledger_rows
from campfire.modules.memory.store import MemoryEpisode, read_timeline, write_episode

#: identity 的归属：记忆是关于使用者自身的时间线经验，按账号分区
#: （`group_id = account_id`），不随支持对象分区——一个账号多个支持对象时
#: 记忆共享（见 docs/技术设计/decisions/通用记忆归属为账号.md）。分区键由登录态
#: 决定，不接受调用方传入。
#:
#: 不得承担：承载档案内容；跨账号共享。
#:
#: graph 的已核实失败语义（见 docs/技术栈设计.md 第 5 节与 docs/TODO.md `TECH-05`）：
#:
#: - 图库写失败不得回滚已完成的主事务状态；写入在请求路径之外执行，
#:   请求只负责与业务数据同事务地写入待处理记录。
#: - Graphiti 的 episode 写入没有官方重试或幂等承诺，幂等须由我们自建并实测；
#:   且 episode 的身份是 `uuid` 而非 `name`（落库为 `MERGE {uuid: $uuid}`），
#:   但同 uuid 的 `MERGE ... SET` 是整节点覆盖、没有「已存在则跳过」语义，
#:   而 `add_episode(uuid=...)` 又要求节点已存在（内部先 `get_by_uuid`）。
#:   因此幂等靠我方「已写入」标记，落地形状见通用记忆第 3 节。
#: - 过期或被推翻的内容不得作为当前依据。
#: - 版本口径：安装要求里的「FalkorDB 1.1.2」是 Graphiti 自己的客户端依赖
#:   （`graphiti-core` 声明 `falkordb>=1.1.2,<2.0.0`），不是服务器版本；
#:   镜像按实际存在的 tag 固定（见 docs/技术栈设计.md 第 2 节）。
#:
#: 实测环境：graphiti-core 0.30.2、falkordb 客户端 1.7.1、FalkorDB 镜像
#: `v4.20.7-alpine`（graph 模块 42007、vectorset 模块 1）。
#:
#: 拥有的用例（见 docs/项目结构设计.md 第 6 节）：通用记忆的写入与读取、
#: 时间演变与失效判定。存储是 Graphiti + FalkorDB。
#:
#: 已实现（2026-09-29）：`errors.py`（异常层次）、`graph.py`（Graphiti +
#: FalkorDB 装配：驱动缓存、TokenHub 三客户端、空重排器）、`identity.py`（账号分区键
#: 与确定性 episode uuid）、`models.py` + 迁移（删除账本表，含词表 CHECK）、
#: `ledger.py`（删除过滤与删除写入端 `record_deletion`）、`deletion.py`
#: （删除与纠正两个用例：`delete_episode` / `correct_episode`）、`store.py`
#: （时间线回看与 episode 写入）、`derived.py`（应急预注入的派生事实取数与时效过滤）、
#: `consumer.py`（Worker 侧消费：`pending_write` → 图库）。
#:
#: 仍缺：记忆侧的工具契约与 `tools/` 包装（含 `delete_memory`）——即模型还调不到
#: 这些用例，登记于 TODO `TECH-22`。图库物理清理延期（账本过滤已保证语义删除生效）。
__all__ = [
    # 异常
    "MemoryConfigurationError",
    "MemoryDataError",
    "MemoryModuleError",
    "MemoryUnavailableError",
    # 身份
    "AccountId",
    "AccountIdError",
    "EpisodeUuid",
    "PendingId",
    "derive_episode_uuid",
    "to_account_id",
    # 装配
    "MemoryGraph",
    "build_memory_graph",
    # 读路径：时间线回看
    "MemoryEpisode",
    "read_timeline",
    # 写路径
    "write_episode",
    # 读路径：应急预注入
    "DerivedFact",
    "EmergencyMemory",
    "EMERGENCY_MEMORY_CHARS",
    "EMERGENCY_MEMORY_LIMIT",
    "read_emergency_facts",
    # 删除账本
    "DELETED_KEYS_LIMIT",
    "DeletionOutcome",
    "DeletionRecord",
    "deleted_episode_keys",
    "record_deletion",
    # 账号注销时的记忆清除（实现 core/auth 的 purger 端口）
    "MemoryAccountPurger",
    "delete_ledger_rows",
    # 删除与纠正用例
    "DeletionResult",
    "correct_episode",
    "delete_episode",
]
