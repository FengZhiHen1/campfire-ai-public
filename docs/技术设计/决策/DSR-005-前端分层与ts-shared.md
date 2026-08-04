# DSR-005：前端保持 views/logics 分层，引入 ts-shared

> **状态**：已由 [DSR-006](./DSR-006-项目结构v3目标态.md) 取代（2026-08-04）——views/logics 两层演进为 domain/application/viewModel/view/infrastructure 物理五层；`ts-shared` 纯类型定位维持有效。
>
> ~~**偏离说明**~~：（历史记录）本决策针对 Taro 小程序前端作出；react-web 曾沿用 views/logics 形态。

## 上下文

项目结构 v1.0 前端采用 views/logics 硬隔离（DS-006），这是整个架构中最严格的分层约束。SAP 前端使用 features/ 单层组织（组件与逻辑混合）。

## 决定

维持 views/logics 分层，同时引入 `packages/ts-shared/` 存放跨项目共享的类型与枚举。

## 理由

1. views/logics 分离使组件成为"Dumb Component"——高度可测试、可复用、可替换；
2. Hooks 作为唯一桥接点形成了清晰的前端内部 API 契约；
3. `ts-shared` 解决跨项目类型复用（未来 H5 管理后台可直接引用同一套类型定义），不与 views/logics 分层冲突。

## 后果

`ts-shared` 仅包含纯类型和枚举，不含任何运行时逻辑。`logics/shared/types/` 中的应用级类型（如 Store State 类型）保留在原位，不迁入 `ts-shared`。

## 重访条件

随 ADR-002 前端形态重访一并评估；或前端应用数量增多、共享类型出现跨端冲突时。
