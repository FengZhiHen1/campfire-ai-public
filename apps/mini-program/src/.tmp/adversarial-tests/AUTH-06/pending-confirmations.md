# AUTH-06 实现偏差确认清单

> 生成时间：2026-05-27
> 实现阶段：Phase 2（按设计文档优雅实现）

---

## 确认项 1：Store 额外 action

**偏差类型**：设计文档兼容性扩展

**描述**：
设计文档和落地规范标注 `SessionStore` 包含 5 个 action 方法：
1. `setAuthenticated` — 重置 failCount 为 0
2. `setRefreshing`
3. `setUnauthenticated`
4. `incrementFailCount`
5. `resetFailCount`

实际实现新增了 2 个辅助 setter，未计入 5 个核心 action 范围：
- `setUser(user: SessionUser | null)` — 设置当前用户信息
- `restoreAuthenticated(tokenPair: TokenPair)` — 恢复 authenticated 状态但保留 refreshFailCount

**必要性**：
- `setUser`：用户信息（userId、roles）需要独立于 tokenPair 设置，冷启动恢复和续期成功后均需单独调用
- `restoreAuthenticated`：续期软失败（failCount < 3）时需回到 authenticated 但保留计数，`setAuthenticated` 会清零计数，需独立方法

**风险**：无。此为对内实现扩展，不影响对外契约（useAuthReturn、httpClient）。

---

## 确认项 2：IRequestResponse 接口扩展

**偏差类型**：契约兼容性扩展

**描述**：
`docs/contracts/AUTH-06/httpClient.json` 定义的 `request<T>` 返回类型为 `Taro.request.SuccessCallbackResult<T>`。

实际实现的 `IRequestResponse<T>` 接口包含以下字段：
```typescript
{
  data: T;
  statusCode: number;
  header: Record<string, unknown>;
  errMsg: string;       // ← 契约中未显式列出，但为 Taro 平台标准字段
}
```

**必要性**：
`errMsg` 是 `Taro.request.SuccessCallbackResult` 的内置字段，Taro 请求总是返回此字段。在接口定义中显式声明可避免 TypeScript 类型访问错误。

**风险**：无。`errMsg` 字段是对 Taro 平台类型的兼容，不改变 `httpClient.request()` 的调用方式。

---

## 确认项 3：tokenManager.refreshTokens 的网络断开检测

**偏差类型**：设计文档一致性说明

**描述**：
落地规范 §1.9.2 异常 5 要求调用 `wx.getNetworkType()` 检测网络断开，若返回 `'none'` 则不计入 `refreshFailCount`。

当前 mock 实现（AUTH-03 后端未落地）中未实现此逻辑，标记为 **TODO**：
```typescript
// TODO: AUTH-03 真实 API 就绪后，在 refreshTokens 的 catch 块中添加：
// const networkType = await Taro.getNetworkType();
// if (networkType.networkType === 'none') {
//   // 网络断开，不计入 failCount，恢复 authenticated
//   store.restoreAuthenticated(currentTokenPair);
//   throw new RefreshInProgressError('Network unavailable, will retry when online');
// }
```

**原因**：
mock 实现在 `try` 块内直接 resolve mock 数据，不会触发 catch 块的网络断开逻辑。真实 API 集成时需补充此检测。

**风险**：
真实 API 集成时若遗忘此检测，用户在完全无网络环境下 3 次 API 调用后会被强制登出，而非优雅等待网络恢复。这是一个需要集成阶段重点关注的点。

---

## 确认项 4：登录接口路径约定

**偏差类型**：假设标注

**描述**：
设计文档和落地规范引用了 `POST /api/v1/auth/login` 作为 AUTH-02 登录接口，`POST /api/v1/auth/refresh` 作为 AUTH-03 续期接口。

当前 mock 实现未使用真实 API 路径发起请求，而是直接返回 mock 数据。代码中已用 `// TODO: AUTH-02/AUTH-03 后端就绪后替换` 注释标注需要修改的位置。

具体位于：
- `tokenManager.ts` 的 `refreshTokens()` 方法
- `useAuth.ts` 的 `login()` 方法

**假设**：
AUTH-02 的 API 路径为 `/api/v1/auth/login`，AUTH-03 的 API 路径为 `/api/v1/auth/refresh`，请求/响应格式与意图文档一致。

**风险**：
若 AUTH-02 或 AUTH-03 最终落地的 API 路径或请求/响应格式有变化，需同步修改两处。

---

## 确认项 5：base64 编解码自定义实现

**偏差类型**：技术选择说明

**描述**：
`storage.ts` 中的 `base64UrlDecode` 和 `base64UrlEncode` 函数使用自定义实现（查表法），未使用 `atob`/`btoa` 或 `Taro.base64ToArrayBuffer`。

**原因**：
微信小程序环境中 `atob`/`btoa` 的可用性因基础库版本而异（部分低版本不支持）。自定义实现提供跨版本兼容性，且仅用于 JWT mock 生成和 payload 解析。

**风险**：
自定义 base64 实现对非 ASCII 字符（如中文）的解码可能存在问题。但 JWT payload 通常仅包含 ASCII 字符（JSON），且 mock token 的 payload 也仅含 ASCII，因此风险极低。

---

## 确认项 6：useAuth 中 tokenPair 的订阅

**偏差类型**：实现细节说明

**描述**：
`useAuth()` Hook 同时订阅了 `sessionState`、`user` 和 `tokenPair` 三个独立 selector，但 `tokenPair` 仅用于组件重渲染触发，未在返回接口 `UseAuthReturn` 中暴露。

**原因**：
当续期成功或登录后 `tokenPair` 更新时，订阅 `tokenPair` 能确保 `login`/`logout` 的 `useCallback` 引用正确更新（虽然两者均使用 `useSessionStore.getState()` 而非闭包）。此订阅主要作为安全网，防止极端时序下的过期闭包问题。

**风险**：
`tokenPair` 的每次变更都会触发组件重渲染。如果 tokenPair 频繁更新（如短时间内多次续期），可能造成不必要的渲染。但在正常场景下，tokenPair 仅通过登录或续期更新，频率极低，影响可忽略。

---

## 总结

| 编号 | 类型 | 严重性 | 需用户裁决 |
|------|------|--------|-----------|
| 1 | 扩展（Store 额外 action） | 低 | 否 |
| 2 | 兼容性扩展（errMsg 字段） | 低 | 否 |
| 3 | TODO 标记（网络断开检测） | 中 | 否（需集成时关注） |
| 4 | 假设标注（API 路径） | 中 | 否（需集成时关注） |
| 5 | 技术选择说明（自定义 base64） | 低 | 否 |
| 6 | 实现细节说明（tokenPair 订阅） | 低 | 否 |

**结论**：6 项均为预期内的合理偏差或实现细节说明，无需用户立即裁决。确认项 3 和 4 在真实 API 集成阶段需要关注。
