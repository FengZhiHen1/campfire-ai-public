"""py-indexing — CASE-04 案例向量化入库模块。

提供审核通过案例的异步索引入库流水线：
1. 投递：enqueue_index_task() 将 case_id 投递到 Redis List
2. 消费：Worker 协程异步消费队列，执行文本组装 + 向量嵌入 + pgvector 写入

外部接口：
    - enqueue_index_task(case_id) -> dict  — CASE-03 审核通过后调用
    - manual_retry_index(case_id) -> dict  — 管理端手动重新索引

内部模块：
    - chunk_builder: 四要素拼接 + PII 最终防线校验
    - embedding_client: 阿里 text-embedding-v4 HTTP 调用
    - index_writer: pgvector 索引写入
    - worker: 单例 Worker 协程（lifespan 启动/停止）
    - models: Pydantic 数据模型
    - exceptions: 异常类
"""

from py_indexing.service import enqueue_index_task, manual_retry_index
from py_indexing.worker import start_worker, stop_worker

__all__ = [
    "enqueue_index_task",
    "manual_retry_index",
    "start_worker",
    "stop_worker",
]
