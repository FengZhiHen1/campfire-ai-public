# @contract
"""api-server 危机分级判定 — Protocol 接口定义。

模块: app.modules.crisis.protocols
职责: 定义可替换功能组件的结构性子类型（Protocol）。
      实现者不需要显式继承，只需满足接口签名即可。
      与 crisis_contract.py 的区别：Protocol 用于可替换的叶子组件（如 AC 自动机匹配器），
      ABC 用于需要强制模板方法（前置→执行→后置）的核心流程（如 CrisisJudgmentPipeline）。

数据来源:
  - 无外部数据来源（纯接口定义）

边界:
  - 依赖: typing.Protocol（Python 标准库）
  - 被依赖: rule_engine_layer.py（注入 KeywordMatcher 实现），test-generator（Mock 实现）

禁止行为:
  - 禁止在 Protocol 中定义 @final 方法（Protocol 不支持模板方法模式）
  - 禁止在 Protocol 中引入具体实现（包括默认值逻辑）
"""

from __future__ import annotations

from typing import Any, Protocol


class KeywordMatcher(Protocol):
    """关键词匹配器接口契约。

    定义 AC 自动机匹配器的核心接口。规则引擎层依赖此 Protocol 而非
    具体 AhoCorasickMatcher 类，使单元测试可注入 mock 匹配器。
    """

    def search(self, text: str) -> list[dict[str, Any]]:
        """在文本中执行关键词匹配。

        输入约束:
          - text: 待扫描文本，非空字符串
        输出约束:
          - list[dict]: 匹配结果列表，每项含 keyword, keyword_id, category,
            trigger_rule_id, start_pos, end_pos, negation_filtered
        异常:
          - RuntimeError: 匹配器尚未加载关键词词库
        """
        ...

    @property
    def is_loaded(self) -> bool:
        """匹配器是否已成功加载关键词词库。"""
        ...

    @property
    def keyword_count(self) -> int:
        """已加载的关键词数量。"""
        ...


__all__ = ["KeywordMatcher"]
