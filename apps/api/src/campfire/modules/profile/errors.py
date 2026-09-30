"""个性化档案的异常层次。

职责：定义 `ProfileError` 家族，让调用方靠异常类型而非错误消息文本区分失败类别。
边界：授权失败的类型在 `core/authz`（不在此处重复定义）；本模块只放业务与输入错误。
参考：docs/技术设计/technical-details/个性化档案.md 第 7 节（失败语义）。
"""

from __future__ import annotations


class ProfileError(Exception):
    """个性化档案的统一异常基类，便于上层一句 `except ProfileError` 收口。

    为什么需要统一基类：调用方（工具的包装层、档案面端点）要区分「输入不合法」
    （不该重试）与「存储不可用」（可重试），而判据只能是异常类型——
    靠错误消息文本判断会在改文案时静默失效（与 `modules/memory` 同一分层思路）。
    """


class ProfileDataError(ProfileError):
    """输入或载荷不满足条目的形状约束。

    与基础设施故障分开：这类失败重试不会变好，调用方应当直接拒绝请求
    （档案面契约第 1 节的 422）。

    诊断字段:
      - operation: 失败的操作名；
      - detail: 人可读的原因（不含使用者内容）。
    """

    def __init__(self, message: str, *, operation: str, detail: str) -> None:
        """记录操作名与人可读的原因。"""
        self.operation = operation
        self.detail = detail
        super().__init__(message)


class InferredCannotBeConfirmedError(ProfileDataError):
    """推断被尝试写成已确认（或直接进稳定层）：请求被拒绝，而不是被降级改写。

    `RQ-MEM-04` 与个性化档案第 3 节的硬约束：`system_observation` 与 `ai_inference`
    不得写成 `confirmation = confirmed`。拒绝而不是降级改写，是因为静默降级会让调用方
    以为「我提交的是确认过的事实」——回执与事实不符。

    单独成型是为了让调用方能给出精确的错误码：它是可预期的调用错误，
    不是数据损坏。
    """


class ProfileItemNotFoundError(ProfileError):
    """条目不存在，或其状态不允许该操作。

    两种情况合并成一个类型是有意的：调用方对它们的处置相同（不能推进），
    而档案面契约把「条目不存在」与「越权」都归为 404 且文案相同——
    区分它只会制造枚举通道。需要区分时按 id 再查一次即可，本模块不为此
    增加一条「先查后改」的路径。

    诊断字段:
      - item_id: 条目标识；
      - reason: 不能推进的原因。
    """

    def __init__(self, item_id: object, reason: str) -> None:
        """记录条目标识与原因。"""
        self.item_id = item_id
        self.reason = reason
        super().__init__(f"档案条目 {item_id!r} 无法处理：{reason}")


__all__ = [
    "InferredCannotBeConfirmedError",
    "ProfileDataError",
    "ProfileError",
    "ProfileItemNotFoundError",
]
