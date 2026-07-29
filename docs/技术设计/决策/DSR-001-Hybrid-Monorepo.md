# DSR-001：采用 Hybrid Monorepo（厚 package、薄 app）而非纯模块化单体

> **状态**：有效（2026-05-24 决策，演进 [ADR-004](./ADR-004-模块化单体.md) 的组织形态）

## 上下文

项目结构 v1.0 将所有代码放在 `apps/api-server/app/` 内（modules + infrastructure + core），形成"厚 app"。worker 嵌入 api-server 内部，缺少 `packages/` 共享层。

## 决定

v2.0 重构为 Hybrid Monorepo，参考 SAP 项目结构。

## 理由

1. ORM 模型、DTO、RAG 引擎、LLM 客户端被 api-server 和 worker 共同需要，集中在 `packages/` 避免代码副本；
2. 独立 worker app 为未来独立扩缩容预留空间；
3. uv + pnpm 双工作空间在各自生态内管理依赖，避免工具冲突；
4. 未来 `apps/admin-web/` 或其他服务可零成本复用已有 packages。

## 后果

需维护两套 workspace 配置；packages 包修改可能同时影响多个 apps，需全量回归测试；跨生态契约无法通过类型系统强行同步。

## 重访条件

package 数量膨胀到维护成本超过复用收益，或出现需要独立技术栈的新应用时。
