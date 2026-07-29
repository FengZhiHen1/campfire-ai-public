# DSR-002：ORM 模型与 Pydantic Schema 集中管理

> **状态**：有效（2026-05-24 决策）

## 上下文

项目结构 v1.0 将 models 和 schemas 分散在各 `modules/*/` 目录下，各模块独立维护自己的数据定义。

## 决定

v2.0 将全部 ORM 模型迁入 `packages/py-db/models/`，全部 Pydantic DTO 迁入 `packages/py-schemas/`。

## 理由

1. Alembic 迁移需要全局视角，分散的模型定义导致迁移脚本容易遗漏；
2. 跨模块查询（如 consult 模块需要 profiles 数据）时，集中管理避免循环 import；
3. `py-schemas` 作为前后端数据契约的单一真相来源，便于与 `ts-shared` 对齐。

## 后果

按业务域拆分的文件组织在 models 和 schemas 层仍然保留（`models/consult.py`、`schemas/consult.py`），不会变成单个巨型文件。

## 重访条件

单一业务域膨胀到需要独立服务时，随服务拆分迁出对应模型与契约。
