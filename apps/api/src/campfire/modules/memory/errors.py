"""通用记忆的异常层次。

归属（见 docs/项目结构设计.md 第 6 节）：本模块拥有「通用记忆的写入与读取、时间演变与失效判定」。失败语义的真源是
`docs/技术设计/technical-details/通用记忆.md` 第 4、6、7 节与
`docs/技术设计/technical-details/写入路径.md` 第 6 节。
边界：调用方（工具层与应急预注入）靠异常类型区分「图库不可用」与「没有记忆」——理由见 `MemoryModuleError`。
参考：`docs/技术设计/technical-details/通用记忆.md` 第 4、6、7 节。
"""

from __future__ import annotations


class MemoryModuleError(Exception):
    """通用记忆的统一异常基类，便于上层一句 `except MemoryModuleError` 收口。

    为什么需要统一基类：调用方（工具层与应急预注入）需要一句话区分
    「图库不可用」与「没有记忆」——前者必须降级标注，后者是正常空值。
    两者的判据只能是异常类型，不能靠错误消息文本。

    为什么不叫 `MemoryError`：那是 Python 内建异常的名字，同名会遮蔽它——
    本模块内任何 `except MemoryError` 都会捕捉到错误的对象（内建语义是内存耗尽），
    是典型的静默错误捕获。名字让出一格，避免这类陷阱。
    """


class MemoryConfigurationError(MemoryModuleError):
    """记忆的配置不可用：缺图库连接信息或凭据。

    与 `EmbeddingConfigurationError` 同属「启动期/首次调用就该暴露」的一类，
    不可能靠重试解决，因此不归入「图库不可用」的降级路径。
    """


class MemoryUnavailableError(MemoryModuleError):
    """图库不可用：连接失败、查询失败或超时。

    必须与「没有记忆」区分（通用记忆第 6 节）：图库不可用时明确标注该来源
    不可用，不得静默当作「没有记忆」。注意 `EntityEdge.get_by_group_ids` 对
    空分区也抛异常（实测 `GroupsEdgesNotFoundError`），因此读取侧必须把
    该情形转成空结果而不是本异常——两条读路径都自建 Cypher，从而根本不经过那个
    方法（见 `derived.py` 的说明：自建的理由之一就是它）。

    诊断字段:
      - operation: 失败的操作名（如 `read_timeline`），供日志定位；
      - cause: 底层异常的类型名。只记类型名，不复述连接串或凭据
        （AGENTS.md 安全条款：日志与错误消息不复述凭据）。

    原始异常对象经 `raise ... from exc` 承载（`__cause__`）：`cause` 字段
    只有类型名，便于日志 grep 且不泄漏连接串；而排查需要完整堆栈时读 `__cause__`
    即可。两者分工明确，不要为了「记全一点」把连接串塞进 `cause`。
    """

    def __init__(self, message: str, *, operation: str, cause: str) -> None:
        """记录操作名与底层异常类型名。"""
        self.operation = operation
        self.cause = cause
        super().__init__(message)


class MemoryDataError(MemoryModuleError):
    """图库中的数据不合法，读路径无法解释。

    实测场景：episode 的 `source` 若不是合法 `EpisodeType`，
    `retrieve_episodes` 会抛 `NotImplementedError`（异常类型与语义完全无关，
    且是写入期脏数据、读取期才炸）。这类情形必须转成明确的领域错误，
    而不是把裸 `NotImplementedError` 泄漏给调用方。

    诊断字段:
      - operation: 失败的操作名；
      - detail: 人可读的原因。
    """

    def __init__(self, message: str, *, operation: str, detail: str) -> None:
        """记录操作名与人可读的原因。"""
        self.operation = operation
        self.detail = detail
        super().__init__(message)


class EpisodeKeyOwnedByAnotherAccountError(MemoryDataError):
    """该 `episode_key` 已被别的账号记入删除账本：本账号的删除不会生效。

    为什么单立一个类型：删除面要把它映射成 404 与「不存在」同形（越权与不存在必须
    逐字同文案），而同一个基类的其它成员（形状非法、账本状态不一致）不该被这样说。
    两者的判据只能是异常类型，不能靠错误消息文本（见 `MemoryModuleError`）——
    靠文案匹配时改一个字的措辞就会让跨账号命中静默降级成「标识形状非法」。

    成因：`episode_key` 由 uuid5 从 `pending_id` 派生，而 `pending_id` 只要求是
    非空短字符串，账本的唯一约束又是全局的。因此两个账号拿到同一个 `pending_id`
    时会派生出同一个 key（见 `ledger.record_deletion` 的 Note）。

    失败是 fail-closed 的：宁可让第二个账号删不掉并如实报「不存在」，
    也不能静默幂等——那会让一次没生效的删除看起来成功。
    """


__all__ = [
    "EpisodeKeyOwnedByAnotherAccountError",
    "MemoryConfigurationError",
    "MemoryDataError",
    "MemoryModuleError",
    "MemoryUnavailableError",
]
