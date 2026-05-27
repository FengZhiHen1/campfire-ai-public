"""py-rag 索引子包 — 案例向量化入库管线。

提供审核通过案例的异步索引入库流水线：
1. 投递：enqueue_index_task() 将 case_id 投递到 Redis List
2. 消费：Worker 协程异步消费队列，执行文本组装 + 向量嵌入 + pgvector 写入

外部接口：
    - enqueue_index_task(case_id, db_session) -> dict
    - manual_retry_index(case_id, db_session) -> dict
    - start_worker(app) -> None
    - stop_worker(app) -> None
"""

from py_rag.indexing.service import enqueue_index_task, manual_retry_index
from py_rag.indexing.worker import start_worker, stop_worker

__all__ = [
    "enqueue_index_task",
    "manual_retry_index",
    "start_worker",
    "stop_worker",
]
