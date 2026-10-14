# apps/web —— React H5（一期唯一前端）

## 当前状态：**已落地**（下面这段是 2026-10-06 的旧状态记录）

> **【2026-10-15 订正】** 本目录**已有工程与实现**：`package.json`、`vite.config.ts`、
> `tsconfig.json`、`src/`（`app/`、`features/`、`shared/`、`infrastructure/`）、`tests/`、
> `e2e/`、`e2e-real/`、`playwright.config.ts`。下文「尚无代码与 `package.json`」**已不成立**；
> 保留它只为记录当时的停工理由与「开工前必须先解决」三条的由来。

~~本目录**尚无代码与 `package.json`**。~~ 此前停在这里的理由已经消失：

`docs/design/` 的视觉契约三件套已于 **2026-10-06 重建并经用户确认**——`DESIGN.md`（含品牌图标、手机端定调、craft 强制清单）、`tokens.css`（61 个 token）、`components.html`（1561 行，含项目组件清单）。它是唯一权威（[项目结构设计](../../docs/项目结构设计.md)第 9 节），实现侧不得另行定义色值与间距。

因此**前端可以动工**。当前缺的是工程搭建，不是设计依据：

1. `package.json` 与构建链（React 19 + Vite；assistant-ui 版本在 `pnpm install` 时锁定，其 `data-*` part 等 API 已核实存在但**未在本地跑过**，落地前以实际版本复核）。
2. token 同步与断言：构建期把 `docs/design/tokens.css` 同步到 `shared/styles/tokens.css`，并有检查断言两份逐字一致（生成物、不手改）。
3. 线格式类型：后端产出 OpenAPI 之前可先手写于 `shared/`，就绪后切换为生成并删除手写副本。

## 后端契约的现状（决定哪些页面能开工）

| 页面 | 后端契约 | 能否开工 |
|---|---|---|
| 登录与注册 | 认证不建面，路由由 SuperTokens SDK 挂载 `/auth/*`（[认证与账号](../../docs/技术设计/technical-details/认证与账号.md)第 5 节） | 能 |
| 首页、设置页、使用说明 | 静态内容；记忆页入口在设置页 | 能 |
| 会话列表页、对话页、应急表单页 | [咨询面 HTTP/SSE 契约](../../docs/技术设计/面/consult/HTTP与SSE契约.md) | 能 |
| 档案页、记忆页 | [档案面](../../docs/技术设计/面/profile/档案面HTTP契约.md)、[记忆面](../../docs/技术设计/面/profile/记忆面HTTP契约.md) | 能 |
| 案例库浏览页 | [资料库面](../../docs/技术设计/面/profile/资料库面HTTP契约.md) | 能（但案例侧未实现、`EVID-F` 未录入前只有空态） |

**三个组件仍无数据来源**：提问卡、行动卡、思考区。它们的交互与页面设计已定，但 `question` / `action_card` / `reasoning_delta` 三个**事件类尚未落地**（载荷形状已由[通用基座](../../docs/技术设计/technical-details/通用基座.md)第 7.1／7.2／7.3 节定义）。组件可按载荷形状先写，但无法联调。

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

1. **构建链**：`package.json`、Vite、React 19、vitest + Testing Library；assistant-ui 版本在
   `pnpm install` 时锁定（其 `data-*` part、`ThreadHistoryAdapter` 等 API 已核实存在，
   但**未在本地跑过**，落地前以实际版本复核）。
2. **token 同步与断言**：构建期把 `docs/design/tokens.css` 同步到 `shared/styles/tokens.css`
   （生成物、不手改），并有检查断言两份逐字一致。
3. **线格式类型**：后端产出 OpenAPI 之前可先手写于 `shared/`，就绪后切换为生成并删除手写副本。

> 上述三条都是**工程搭建**，不是设计缺口：视觉契约与后端契约均已成文（见上文两节）。
