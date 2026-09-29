"""运行编排的错误类型。

这里只有**装配错误**——它们在进程启动或首次运行时暴露，且不可能靠重试解决。
一次运行的失败不是异常，而是 ``run_failed`` 事件（带错误码），见
:mod:`campfire.agent.runtime.events`。
"""

from __future__ import annotations


class RuntimeAssemblyError(Exception):
    """运行编排的装配契约被破坏（缺协作者、标识为空、配置自相矛盾）。"""


class SessionConfigurationError(RuntimeAssemblyError):
    """会话无法建立：标识为空，或没有可用的数据库引擎。

    引擎由装配处从 ``core/db`` 注入——``agent/*`` 不允许依赖 ``core/db``
    （docs/项目结构设计.md 第 7 节），因此基座**不自己创建连接池**。
    """
