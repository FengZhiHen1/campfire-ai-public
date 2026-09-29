# apps/web —— React H5（一期唯一前端）

## 当前状态：**只有目录占位，没有构建链**

本目录下没有任何代码，也没有 `package.json`。这是刻意的：

`docs/项目结构设计.md` 第 9 节规定 **`docs/design/tokens.css` 是视觉契约的唯一权威**，
构建期同步到 `shared/styles/tokens.css` 并有断言两份逐字一致，**实现侧不得另行定义
色值与间距**。而该契约目录当前**不存在**（v3.0 的旧契约已随基线归档，不得作为当前依据）。

在契约重建之前动工，必然要凭感觉写死色值与间距——那正是设计明令禁止的。
因此前端先停在占位状态。

## 目标结构（见 `docs/项目结构设计.md` 第 9 节）

```text
apps/web/src/
├── app/                       # 应用外壳：路由、Provider、装配
├── features/<feature>/
│   ├── domain/                # 无框架业务类型与纯规则
│   ├── application/           # 用例与端口；不导入框架与 HTTP 库
│   ├── viewModel/             # 交互状态与 Hooks；对话适配与 store
│   └── view/                  # 页面与组件
├── shared/                    # 跨特性复用：ui 原语、生成的线格式类型、tokens
└── infrastructure/            # 端口实现：HTTP/SSE、凭据、本地存储
```

一期特性：`accounts`、`consult`、`library`、`profile`、`memory`。

## 依赖方向与禁令（第 9 节）

- `app` → `features` / `shared` / `infrastructure`。
- `features/<f>/view` → 本特性 `viewModel` → `application` → `domain`；
  跨特性只经对方的 `application` 或 `shared`。
- `application` **不得**导入任何框架或 HTTP 库。
- `view` **不得**直接调用 HTTP、读写凭据或跨层导入 `infrastructure`。
- `viewModel` **不得**导入 `view`。

## 开工前必须先解决

1. **视觉契约缺失**：`docs/design/tokens.css`、`components.html`、`DESIGN.md` 需按
   design-spec-workshop 的产物形态重建。这也是 CI 里视觉契约检查当前被降级为告警的原因。
2. **页面设计文档缺失**：交互与页面视觉尚未成文；`TODO.md` 第四节仍列着
   「支持对象的建立与切换交互」等待定项。
3. **线格式类型**：后端产出 OpenAPI 之前可先手写于 `shared/`，就绪后切换为生成并删除手写副本。
