"""Worker 任务模块。

每个任务对应一个后台异步处理单元，委托 py-rag 的契约实现完成实际工作。
"""

from worker.tasks.case_indexer import index_case

__all__ = [
    # 任务函数
    "index_case",
]
