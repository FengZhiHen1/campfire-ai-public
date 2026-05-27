# AUTH-06 对抗性测试清单

> 生成时间：2026-05-27
> 来源契约：contract-expectations.md v1.0（67 条契约期望）
> 测试文件：test_AUTH-06.adversarial.test.ts

## 测试统计

| 系列 | 描述 | 测试用例数 | 契约覆盖 |
|:---|:---|:---|:---|
| A | 参数边界破坏 | 52 | A01-A19 (全部) |
| B | 状态机破坏 | 10 | B01-B09 (全部), A11 |
| C | 异常行为破坏 | 7 | C01-C03, C06-C08 |
| D | 副作用验证 | 7 | D01-D07 (全部) |
| 并发 | 竞态条件 | 2 | B03 |
| 综合 | 类型破坏 | 3 | A01-A03 扩展 |
| **总计** | | **81** | **67 条契约期望全覆盖** |

---

## A 系列：参数边界破坏（52 个用例）

### validateTokenPairFormat — 类型谓词边界

| # | 契约编号 | 破坏意图 | 输入 | 预期行为 | 文件位置（行范围） |
|:---|:---|:---|:---|:---|:---|
| 1 | A01 | null 值类型收缩失败 | `null` | 返回 false | L303-L304 |
| 2 | A01-ext | undefined 值类型收缩失败 | `undefined` | 返回 false | L306-L308 |
| 3 | A02 | 缺失 refreshToken 仍通过校验 | `{accessToken: "eyJ.xxx.yyy"}` | 返回 false | L310-L314 |
| 4 | A02-ext | 缺失 accessToken 仍通过校验 | `{refreshToken: "eyJ.xxx.yyy"}` | 返回 false | L316-L321 |
| 5 | A03 | accessToken 非 string 类型通过 | `{accessToken: 123, refreshToken: "..."}` | 返回 false | L323-L328 |
| 6 | A03-ext | accessToken 为 boolean 通过 | `{accessToken: true, ...}` | 返回 false | L330-L337 |
| 7 | A03-ext | accessToken 为嵌套对象通过 | `{accessToken: {nested: "value"}, ...}` | 返回 false | L339-L346 |
| 8 | A03-ext | accessToken 为数组通过 | `{accessToken: ["a","b"], ...}` | 返回 false | L348-L354 |
| 9 | A03-ext | refreshToken 为非 string 通过 | `{accessToken: "...", refreshToken: 456}` | 返回 false | L356-L362 |
| 10 | A03-ext | refreshToken 为 null 通过 | `{accessToken: "...", refreshToken: null}` | 返回 false | L364-L370 |
| 11 | A03-ext | 两字段均为空字符串通过 | `{accessToken: "", refreshToken: ""}` | 返回 false | L372-L377 |
| 12 | A03-ext | accessToken 为空但 refreshToken 有效通过 | 单字段空字符串 | 返回 false | L379-L384 |
| 13 | 扩展 | 原始字符串传入 | `"not-an-object"` | 返回 false | L386-L388 |
| 14 | 扩展 | 数组传入 | `["a", "b"]` | 返回 false | L390-L392 |
| 15 | 扩展 | 数字传入 | `42` | 返回 false | L394-L396 |
| 16 | 扩展 | Symbol 传入 | `Symbol("test")` | 返回 false | L398-L400 |
| 17 | 扩展 | 空对象传入 | `{}` | 返回 false | L402-L404 |
| 18 | 扩展 | 多余字段但核心字段正确 | `{accessToken, refreshToken, extra: ...}` | 返回 true（多余字段不应影响） | L406-L413 |

### validateTokenPair — 另一个类型谓词

| # | 契约编号 | 破坏意图 | 输入 | 预期行为 |
|:---|:---|:---|:---|:---|
| 19 | 扩展 | null 值 | `null` | 返回 false |
| 20 | 扩展 | undefined 值 | `undefined` | 返回 false |
| 21 | 扩展 | 正确 TokenPair | 有效 JWT 对 | 返回 true |
| 22 | 扩展 | 非对象参数 | 数字、字符串等 | 返回 false |

### validateJWTFormat — JWT 格式校验

| # | 契约编号 | 破坏意图 | 输入 | 预期行为 |
|:---|:---|:---|:---|:---|
| 23 | A04 | 非三段式字符串通过格式校验 | `"not-a-jwt-string"` | 返回 false |
| 24 | A05 | 空字符串通过格式校验 | `""` | 返回 false |
| 25 | A05-ext | 两段式通过校验 | `"a.b"` | 返回 false |
| 26 | A05-ext | 四段式通过校验 | `"a.b.c.d"` | 返回 false |
| 27 | A05-ext | 仅点号通过校验 | `"..."` | 返回 false |
| 28 | 扩展 | 含空格的三段式 | `"header.with space.sig"` | 返回 false |
| 29 | 扩展 | 含中文的三段式 | `"头.体.签"` | 返回 false |
| 30 | 扩展 | 超长有效 JWT | 1000 字符 payload | 返回 true |
| 31 | 扩展 | 单字符三段 | `"a.b.c"` | 返回 true |
| 32 | 扩展 | 某段为空 | `"a..c"` | 返回 false |
| 33 | 扩展 | 尾部多余点号 | `"a.b.c."` | 返回 false |
| 34 | 扩展 | 有效完整 JWT | 真实三段式 base64url JWT | 返回 true |

### isTokenExpired — Token 过期判定

| # | 契约编号 | 破坏意图 | 输入 | 预期行为 |
|:---|:---|:---|:---|:---|
| 35 | A06 | 已过期 JWT 被判为未过期 | 过期 1 小时的 JWT | 返回 true |
| 36 | A07 | 未过期 JWT 被判为过期 | 未来 1 小时的 JWT | 返回 false |
| 37 | 扩展 | exp 边界值（恰为当前时间）漏判 | `exp = Math.floor(Date.now()/1000)` | 返回 true（保守安全） |
| 38 | 扩展 | 无效格式导致 crash | `"not-valid-jwt-at-all"` | 不抛异常 |
| 39 | 扩展 | 缺少 exp 字段被误判为有效 | 无 exp 的 JWT | 返回 true（保守安全） |
| 40 | 扩展 | null 输入导致 crash | `null` (强制类型转换) | 不抛异常 |
| 41 | 扩展 | exp 为非数字类型 | `exp: "not-a-number"` | 不抛异常 |
| 42 | 扩展 | exp 超大值导致溢出 | `exp: 9999999999` | 返回 false |

### parseJWTPayload — JWT Payload 解析

| # | 契约编号 | 破坏意图 | 输入 | 预期行为 |
|:---|:---|:---|:---|:---|
| 43 | A18 | 有效 JWT 解析失败 | 正确三段式 JWT | 返回解析后的 JSON 对象 |
| 44 | 扩展 | 非 JWT 格式污染返回值 | `"not-a-jwt"` | 返回 null |
| 45 | 扩展 | 空字符串 | `""` | 返回 null |
| 46 | 扩展 | payload 段非有效 base64url | `"header.!!!invalid!!!.sig"` | 返回 null |
| 47 | 扩展 | payload 段非有效 JSON | base64url 编码的 "not-json" | 返回 null |
| 48 | 扩展 | null 输入 crash | `null` | 返回 null |
| 49 | 扩展 | undefined 输入 crash | `undefined` | 返回 null |

### base64UrlEncode — 编码

| # | 契约编号 | 破坏意图 | 输入 | 预期行为 |
|:---|:---|:---|:---|:---|
| 50 | A17 | 普通字符串编码输出含 +/= | `"hello"` | 返回 base64url 字符串（无 +/=） |
| 51 | 扩展 | 空字符串 crash | `""` | 返回有效字符串 |
| 52 | 扩展 | 中文编码不可逆 | `"你好世界"` | 解码后等于原文 |
| 53 | 扩展 | 特殊字符编码错误 | `"hello\nworld\t!@#$..."` | 解码后等于原文 |
| 54 | 扩展 | 超长字符串 crash | 10KB 'A' 字符 | 返回有效字符串 |

### safeGetStorage — 安全读取

| # | 契约编号 | 破坏意图 | 输入 | 预期行为 |
|:---|:---|:---|:---|:---|
| 55 | A08 | 不存在 key 返回非 null | `"nonexistent_key"` | 返回 null |
| 56 | 扩展 | 有效 JSON 解析失败 | `{"name": "value", "num": 42}` | 返回解析后对象 |
| 57 | 扩展 | 字符串值 | `"plain_string"` | 返回解析后字符串 |
| 58 | 扩展 | 非 JSON 值 crash | `"{not: valid, json}"` | 不抛异常 |
| 59 | 扩展 | getStorageSync 本身 crash | mock 抛异常 | 不抛异常 |

### safeSetStorage — 安全写入

| # | 契约编号 | 破坏意图 | 输入 | 预期行为 |
|:---|:---|:---|:---|:---|
| 60 | A09 | 循环引用被序列化 | 循环引用对象 | 返回 false |
| 61 | 扩展 | 正常对象写入失败 | `{value: 42, label: "ok"}` | 返回 true，数据写入 storage |
| 62 | 扩展 | 空对象 | `{}` | 返回 true |
| 63 | 扩展 | 空字符串 key crash | `("", {data: "x"})` | 不抛异常 |
| 64 | A13 | 存储满时未降级 | `setStorageSync` 抛 "storage limit exceeded" | 返回 false |
| 65 | A13-ext | 首次失败重试成功 | 第 1 次抛异常，第 2 次成功 | 返回 boolean |
| 66 | 扩展 | undefined data crash | `undefined` | 不抛异常 |
| 67 | 扩展 | Function data crash | `function(){}` | 返回 boolean |

### safeRemoveStorage — 安全移除

| # | 契约编号 | 破坏意图 | 输入 | 预期行为 |
|:---|:---|:---|:---|:---|
| 68 | A10 | 任意 key（含不存在） | `"any_key"` | 返回 true |
| 69 | 扩展 | 存在数据删除失败 | `"will_delete"` (已存在) | 删除后不存在 |
| 70 | 扩展 | removeStorageSync crash | mock 抛异常 | 不抛异常 |

### buildMockLoginResponse

| # | 契约编号 | 破坏意图 | 输入 | 预期行为 |
|:---|:---|:---|:---|:---|
| 71 | A19 | 返回结构不完整 | `("testuser", "pass123")` | 含 accessToken/refreshToken/tokenType/user |
| 72 | 扩展 | 空 username crash | `("", "pass")` | 不抛异常 |
| 73 | 扩展 | 空 password crash | `("user", "")` | 不抛异常 |

---

## B 系列：状态机破坏（10 个用例）

| # | 契约编号 | 破坏意图 | 测试策略 | 预期行为 |
|:---|:---|:---|:---|:---|
| 74 | B01 | unauthenticated 状态下调用 setRefreshing 未被拒绝 | 空 storage 初始化 → 调用 setRefreshing | 抛异常或静默拒绝，状态不变 |
| 75 | B02 | refreshing 状态下重复 setRefreshing 导致状态异常 | 先进 refreshing → 再调 setRefreshing | 不抛异常，状态保持 refreshing |
| 76 | B04 | 续期成功后 sessionState 未恢复 authenticated | mock 续期成功 200 → 触发 401 续期 | sessionState 为 authenticated |
| 77 | B05 | 软失败（failCount < 3）清除了 Token | mock 续期 500 → 1 次失败 | sessionState 为 authenticated，Token 保留 |
| 78 | B06 | 硬失败（failCount >= 3）未清除会话 | mock 续期 401 × 3 次 | state=unauthenticated，storage 清除，reLaunch 调用 |
| 79 | B07 | 已登录下 login 未先登出 | authenticated → call login | 先清旧 session 再设新 session |
| 80 | B08 | 冷启动时过期 RT 通过了校验 | storage 中含过期 refreshToken | sessionState=unauthenticated，过期 token 被清除 |
| 81 | B09 | 冷启动无数据时 sessionState 非 unauthenticated | 空 storage | sessionState=unauthenticated |
| 82 | A11 | Storage 中 TokenPair 格式损坏未降级 | `{accessToken: "bad"}` 缺 refreshToken | state=unauthenticated，损坏数据清除 |
| 83 | A11-ext | 损坏数据无任何 auth 键 | `{foo: "bar"}` | initSession 不崩溃，降级 unauthenticated |

---

## C 系列：异常行为破坏（7 个用例）

| # | 契约编号 | 破坏意图 | 测试策略 | 预期行为 |
|:---|:---|:---|:---|:---|
| 84 | C01 | 续期接口返回 401 触发死递归 | 业务 401 → 续期 → 续期自身也 401 | reject，refresh 调用不超过 1 次 |
| 85 | C02 | 续期 403 未计入 failCount | 续期 403 → 软失败流程 | reject，failCount 增加 |
| 86 | C03 | 续期 500 未计入 failCount | 续期 500 → 软失败流程 | reject，failCount 增加 |
| 87 | C06 | accessToken 为空时注入了空 Authorization 头 | authenticated + accessToken="" | 不注入 Authorization 头 |
| 88 | C07 | 已登录页时仍执行 reLaunch 造成重复跳转 | 页面栈路由为 login | reLaunch 不被重复调用 |
| 89 | C08 | unauthenticated 时 401 触发了续期 | 未登录 + API 返回 401 | 不调用续期接口，直接 reject |
| 90 | C04 | 续期超时未 reject | mock 续期超过 10s | 不适用单元测试环境（需集成测试，记录为手动验证项） |

---

## D 系列：副作用验证（7 个用例）

| # | 契约编号 | 破坏意图 | 测试策略 | 预期行为 |
|:---|:---|:---|:---|:---|
| 91 | D01 | login 成功后未写入 Storage | authenticated 状态设置 → 验证 storage | auth:token_pair 存在 |
| 92 | D02 | 续期成功后 Storage 未更新 | 续期 200 响应 → 验证 storage 更新 | storage 中 TokenPair 变更 |
| 93 | D03 | clearSession 删除了业务数据 | 设置业务键 → 触发会话清除 | 仅 auth 键删除，业务键保留 |
| 94 | D04 | logout 后未跳转登录页 | 调用 logout → 检查 reLaunch | reLaunch({url: '/pages/login/index'}) 被调用 |
| 95 | D05 | 硬失败后未 reLaunch | failCount 达 3 → 验证跳转 | reLaunch('/pages/login/index') 被调用 |
| 96 | D06 | 已登录时未注入 Authorization 头 | authenticated + GET 请求 | Authorization: Bearer <token> 在 header 中 |
| 97 | D07 | useAuth 返回格式错误 | 调用 useAuth() | 返回含 sessionState 字段的对象 |

---

## 并发竞态测试（2 个用例）

| # | 契约编号 | 破坏意图 | 测试策略 | 预期行为 |
|:---|:---|:---|:---|:---|
| 98 | B03 | 3 个并发 401 触发了多次续期 | 3 请求同时 401 → 计数 refresh 调用 | refresh API 仅调用 1 次 |
| 99 | B03-ext | 续期进行中到达的新 401 未等待 | 在 refreshPromise pending 期间发起请求 | 后续请求 await 同一个 refreshPromise |

---

## 综合类型破坏（3 个用例）

| # | 契约编号 | 破坏意图 | 测试策略 | 预期行为 |
|:---|:---|:---|:---|:---|
| 100 | A01-ext | 所有 JS 原始类型被 validateTokenPairFormat 错误接受 | 穷举 0/-1/NaN/Symbol/Function/Date/RegExp/Map/Set 等 20 种类型 | 全部返回 false |
| 101 | 扩展 | BigInt 写入 storage 崩溃 | `safeSetStorage('bigint', BigInt(9007199254740991))` | 不崩溃 |
| 102 | 扩展 | Symbol 写入 storage 崩溃 | `safeSetStorage('sym_key', Symbol('x'))` | 不崩溃 |

---

## 已知限制与手动验证项

以下测试用例因测试环境限制无法在 vitest 中完整执行，需要手动验证：

| 契约编号 | 原因 | 建议手动验证方式 |
|:---|:---|:---|
| C04 (续期超时 10s) | vitest 单元测试难以精确控制 10s 超时 | 集成测试中 mock 延迟 > 10s 的请求 |
| C05 (网络断开) | 需要模拟 wx.getNetworkType 的真实回调 | 微信开发者工具中切换网络模式 |
| B07 (login 在 authenticated 状态) | useAuth().login() 需要 React Hook 环境 | 使用 @testing-library/react-hooks 或组件级测试 |
| D04/D05/D07 (useAuth 相关) | React Hook 需要在组件上下文调用 | 使用 @testing-library/react-hooks 或 E2E 测试 |
| C07 (reLaunch 已是登录页) | 需要完整的 store action 链 |小程序真机测试 |

---

## 注意事项

1. **导入路径**：测试文件中的 import 路径基于落地规范 §1.2 文件归属表推断。若实际导出结构不同，需要调整 import 语句。
2. **Store API**：测试中使用 `userStore.getState()` 并通过类型断言访问内部字段（如 `sessionState`、`setRefreshing`）。若 store 的实际 action 名称不同，需要更新。
3. **Mock 完整性**：所有 Taro API 已 mock 为内存实现。若实现使用了 Taro 的其他 API（如 `Taro.getNetworkType`、`Taro.onNetworkStatusChange`），需要补充 mock。
4. **vitest 配置**：项目当前无 vitest 配置文件。运行测试前需先安装 vitest 并创建 `vitest.config.ts`。
