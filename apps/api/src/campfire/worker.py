"""Taskiq Worker 入口。

归属（见 docs/项目结构设计.md 第 7 节）：worker 入口允许依赖 ``core/*`` 与
``modules/{profile,memory}``；**禁止 import ``surfaces/*``，禁止回查业务用例**。

运行模型（见 docs/技术栈设计.md 第 5 节）：全异步，**不引入同步与异步之间的
桥接**；broker 与 HTTP 入口共用同一份构造（``core/jobs.build_broker``）。

一期尚无任务，本文件只完成 broker 装配；任务随各自的消费者落地——待处理记录的
消费、幂等键重试与死信告警见 docs/技术设计/technical-details/写入路径.md。

启动方式：``uv run taskiq worker campfire.worker:broker``
"""

from campfire.core.config import get_settings
from campfire.core.jobs import build_broker

broker = build_broker(get_settings())
