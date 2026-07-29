# DSR-004：Worker 独立为应用

> **状态**：有效（2026-05-24 决策）

## 上下文

项目结构 v1.0 的 worker（`case_indexer.py`）放在 `apps/api-server/workers/` 下，与 API 服务共享同一进程空间和部署单元。

## 决定

v2.0 将 worker 独立为 `apps/worker/`，与 api-server 同级。

## 理由

1. worker 和 api-server 有不同的扩缩容需求——API 需要多副本应对并发，worker 可能只需要单实例；
2. 独立 Dockerfile 允许 worker 使用不同的基础镜像或资源配置；
3. 清晰的进程边界——worker 崩溃不影响 API 服务。

## 后果

MVP 阶段 worker 只有 `case_indexer` 一个任务，独立 app 结构略显"重"。但目录结构成本极低（`apps/worker/` 只有 3-4 个文件），未来收益远大于当前成本。

## 重访条件

异步任务数量增多到需要任务路由/优先级队列，或引入 Celery 等正式任务框架时。
