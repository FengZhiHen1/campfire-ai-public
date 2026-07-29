# ADR-001：后端框架选择 Python/FastAPI

> **状态**：有效（2026-05-23 决策）

## 上下文

项目核心是 RAG + LLM，需要选择后端语言与框架。

## 备选与评价

- **Python/FastAPI**：AI 生态（LangChain/HuggingFace）以 Python 为第一语言；asyncio 原生异步满足 TTFT ≤ 3s 响应要求；转型叙事明确提及 FastAPI，团队认知基础存在。
- **Node.js/NestJS**：前后端同语言，但 AI 生态为第二公民。
- **Go/Gin**：运行时性能最强，但 AI 生态胶水层成本高。

## 决定

Python/FastAPI。

## 后果

- 正面：AI 集成零胶水层；
- 负面：运行时性能弱于 Go/Java，高并发需配合 Gunicorn workers。

## 重访条件

出现 Python 无法承载的并发性能瓶颈，或 AI 编排生态发生根本性迁移时。
