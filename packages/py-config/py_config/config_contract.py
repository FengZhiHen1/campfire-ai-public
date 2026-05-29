"""DEPLOY-05 环境配置管理 — 行为契约（ABC 模板方法）。

定义配置加载器的契约骨架：
- @final load() = 唯一外部入口，校验逻辑不可绕过
- @abstractmethod _do_load() = 实现者填写的实际加载钩子
- 校验器 = 模板提供基线校验，子类通过 super() 叠加

实现者只能覆写 _do_ 前缀的钩子。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar, final

TSettings = TypeVar("TSettings")


class BaseConfigLoader(ABC, Generic[TSettings]):
    """配置加载器契约。

    定义"校验环境 → 加载配置 → 校验结果"的三明治流程。
    外部调用者只能通过 @final load() 获取配置，无法绕过校验。

    Usage:
        class AppSettingsLoader(BaseConfigLoader[AppSettings]):
            def _do_load(self) -> AppSettings:
                return AppSettings()  # pydantic-settings 自动校验
    """

    @final
    def load(self) -> TSettings:
        """加载并校验配置。校验失败时致命退出（sys.exit(1)）。

        此为唯一外部入口，子类不可覆写。
        流程：前置校验 → _do_load() → 后置校验。
        """
        self._validate_preconditions()
        settings = self._do_load()
        self._validate_postconditions(settings)
        return settings

    @abstractmethod
    def _do_load(self) -> TSettings:
        """从配置源加载并校验配置。

        实现者在此填写实际的加载逻辑（如 pydantic-settings 构造）。
        前置/后置校验已由模板方法处理，实现者无需关心。

        Raises:
            pydantic.ValidationError: 配置校验失败时由实现者抛出。
        """
        ...

    def _validate_preconditions(self) -> None:
        """基线前置校验。检查运行时环境是否支持配置加载。

        子类可通过 super() 叠加额外的前置检查。
        """
        pass

    def _validate_postconditions(self, settings: TSettings) -> None:
        """基线后置校验。确保加载结果非空。

        子类可通过 super() 叠加额外的后置检查
        （如生产环境密钥来源检测）。
        """
        if settings is None:
            raise RuntimeError(
                f"{self.__class__.__name__}._do_load() returned None"
            )
