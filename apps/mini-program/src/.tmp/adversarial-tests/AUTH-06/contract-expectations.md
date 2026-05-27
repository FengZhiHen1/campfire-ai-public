# AUTH-06 认证会话管理 契约期望清单

> 来源：AUTH-06-认证会话管理-落地规范.md v1.0
> 冻结时间：2026-05-27 00:00:00

## 参数约束（A 系列）

| 编号 | 契约维度 | 破坏性输入 | 期望行为 | 来源章节 |
|:---|:---|:---|:---|:---|
| A01 | validateTokenPairFormat value 为 null | `null` | 返回 false | §1.9.1 |
| A02 | validateTokenPairFormat 对象缺少 refreshToken | `{accessToken: "eyJ.xxx.yyy"}` | 返回 false | §1.9.1 |
| A03 | validateTokenPairFormat accessToken 为非 string | `{accessToken: 123, refreshToken: "eyJ.xxx.yyy"}` | 返回 false | §1.9.1 |
| A04 | validateJWTFormat token 为非三段式字符串 | `"not-a-jwt-string"` | 返回 false | §1.9.1 |
| A05 | validateJWTFormat token 为空字符串 | `""` | 返回 false | §1.9.1 |
| A06 | isTokenExpired token JWT 已过期 | 已过期的 JWT（exp 时间戳 < Date.now()） | 返回 true | §1.5 |
| A07 | isTokenExpired token JWT 未过期 | 未过期的 JWT（exp 时间戳 > Date.now()） | 返回 false | §1.5 |
| A08 | safeGetStorage key 不存在于 Storage | `"nonexistent_key"` | 返回 null | §1.9.1 |
| A09 | safeSetStorage data 为不可序列化对象 | 循环引用对象 | 返回 false | §1.9.4 |
| A10 | safeRemoveStorage key 为任意字符串 | `"any_key"` | 返回 true | §1.9.1 |
| A11 | initSession Storage 中 TokenPair 格式损坏 | `{accessToken: "bad"}` 缺少 refreshToken | 抛出 Error 恢复为 unauthenticated 状态 | §1.9.1 |
| A12 | setTokens pair 参数为 null | `null` | return early 无副作用，不抛异常 | §1.9.1 |
| A13 | setTokens Storage 写入容量超限 | 模拟 setStorageSync 抛异常 | 清除旧数据重试 1 次后返回 false | §1.9.4 |
| A14 | login username 参数为空字符串 | `""` | 抛出 LoginError | §1.6.1 |
| A15 | login password 参数为空字符串 | `""` | 抛出 LoginError | §1.6.1 |
| A16 | logout 在 unauthenticated 状态下调用 | sessionState 为 unauthenticated | 无异常抛出，安全空操作 | §1.9.5 |
| A17 | base64UrlEncode 输入为普通 ASCII 字符串 | `"hello"` | 返回 base64url 编码字符串 | §1.9.1 |
| A18 | parseJWTPayload token 为有效 JWT | 有效三段式 JWT 字符串 | 返回解析后的 JSON payload 对象 | §1.5 |
| A19 | buildMockLoginResponse 正常凭证 | `("user", "pass")` | 返回 {accessToken, refreshToken, tokenType, user} | §1.7.2 |

## 状态机约束（B 系列）

| 编号 | 契约维度 | 破坏性输入 | 期望行为 | 来源章节 |
|:---|:---|:---|:---|:---|
| B01 | setRefreshing 在 unauthenticated 状态被调用 | sessionState 为 unauthenticated | 抛出状态转换拒绝，sessionState 不变 | §1.8 |
| B02 | setRefreshing 在 refreshing 状态被重复调用 | sessionState 已是 refreshing | 无异常抛出，静默不操作，refreshPromise 不变 | §1.8 |
| B03 | 3 个并发 401 触发续期互斥 | 3 个请求同时在 401 拦截器执行 | 返回：仅发起 1 次 refreshTokens 调用 | §1.9.3 |
| B04 | refreshTokens 成功后的状态转换 | refreshTokens 返回新 TokenPair | 返回：sessionState 变为 authenticated，failCount 归零 | §1.8 |
| B05 | 续期软失败（failCount < 3） | refreshTokens 失败且 failCount < 3 | 返回：sessionState 回 authenticated，Token 不清除 | §1.8 |
| B06 | 续期硬失败（failCount >= 3） | refreshTokens 失败且 failCount >= 3 | 返回：sessionState 变为 unauthenticated，Storage 清除 | §1.8 |
| B07 | login 在已 authenticated 状态下调用 | sessionState 为 authenticated | 返回：先执行登出再登录，最终为 authenticated | §1.6.1 |
| B08 | 冷启动时 Refresh Token 已过期 | Storage 中 refreshToken.exp < now | 返回：sessionState 为 unauthenticated，Storage 清除 | §1.5 |
| B09 | 冷启动时 Storage 无任何数据 | getStorageSync 返回 null | 返回：sessionState 为 unauthenticated | §1.5 |

## 异常行为约束（C 系列）

| 编号 | 契约维度 | 破坏性输入 | 期望行为 | 来源章节 |
|:---|:---|:---|:---|:---|
| C01 | 续期接口自身返回 401 | 续期 URL 的响应 statusCode 为 401 | 返回 rejected Promise（防止死递归） | §1.11 |
| C02 | 续期接口返回 HTTP 403 | 续期响应 statusCode 为 403 | 返回 rejected Promise（计入 failCount） | §1.9.2 |
| C03 | 续期接口返回 HTTP 500 | 续期响应 statusCode 为 500 | 返回 rejected Promise（计入 failCount） | §1.9.2 |
| C04 | 续期请求超时 10s | 续期请求超过 10000ms 无响应 | 返回 rejected Promise 且抛出 Timeout Error | §1.9.2 |
| C05 | 网络断开时续期调用 | wx.getNetworkType 返回 'none' | 返回 rejected Promise（不计入 failCount） | §1.9.2 |
| C06 | authenticated 但 accessToken 为空字符串 | tokenPair.accessToken 为 "" | 返回原请求不注入 Authorization 头 | §1.5 |
| C07 | reLaunch 时当前路由已是登录页 | getCurrentPages 最后一页 route 为 pages/login/index | 返回 void（跳过 reLaunch，仅更新 Store） | §1.9.5 |
| C08 | unauthenticated 状态下收到 401 | sessionState 为 unauthenticated 且 API 返回 401 | 返回 rejected Promise（不触发续期） | §1.5 |

## 副作用验证（D 系列）

| 编号 | 契约维度 | 破坏性输入 | 期望行为 | 来源章节 |
|:---|:---|:---|:---|:---|
| D01 | login 成功后写入 TokenPair 到 Storage | 正常登录 | 无返回值；setStorageSync 写入 auth:token_pair | §1.10.1 |
| D02 | refreshTokens 成功后更新 Storage | 续期成功 | 无返回值；setStorageSync 写入 newPair | §1.5 |
| D03 | clearSession 仅清除认证数据 | 会话清除触发 | 无返回值；removeStorageSync 仅删除 auth 相关键 | §1.11 |
| D04 | logout 后跳转登录页 | 调用 logout() | 无返回值；reLaunch({url: '/pages/login/index'}) 被调用 | §1.10.3 |
| D05 | 硬失败后跳转登录页 | failCount 达到 3 | 无返回值；reLaunch({url: '/pages/login/index'}) 被调用 | §1.10.4 |
| D06 | httpClient.request 注入 Authorization 头 | 已登录时发送 GET 请求 | 返回 config.header.Authorization = Bearer <token> | §1.10.2 |
| D07 | useAuth 返回 sessionState | 任意组件中调用 useAuth() | 返回 'authenticated' 或 'refreshing' 或 'unauthenticated' | §1.6.1 |
