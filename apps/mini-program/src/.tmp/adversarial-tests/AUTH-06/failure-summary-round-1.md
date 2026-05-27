# AUTH-06 失败摘要 — 第 1 轮

> 测试时间：2026-05-27

## 测试结果总览

| 指标 | 数量 |
|:---|:---|
| 全部测试 | 100 |
| 通过 | 78 |
| 失败 | 2 |
| 跳过 | 20 |

## 失败用例（实现缺陷）

### [FAIL-001] safeSetStorage: 循环引用对象导致未捕获异常
- **错误类型**：TypeError: Converting circular structure to JSON
- **涉及函数**：`safeSetStorage(key, data)`
- **违反的契约条款**：A09（循环引用对象应返回 false，不抛异常）
- **根因**：`storage.ts:63` 行 `JSON.stringify(data)` 在 try-catch 块外部执行，循环引用导致同步抛出未捕获异常
- **修复方向**：将 `JSON.stringify(data)` 移入 try-catch 块内部

### [FAIL-002] base64UrlEncode: 中文字符编码不可逆
- **错误类型**：AssertionError（解码结果不等于原始中文输入）
- **涉及函数**：`base64UrlEncode(str)`
- **违反的契约条款**：A17（base64url 编码应正确可逆）
- **根因**：自定义 base64 查表法仅处理单字节字符，未对多字节 UTF-8 字符（如中文）进行预处理
- **修复方向**：在编码前使用 `encodeURIComponent` + 逐字节转换，或使用 `Buffer`/`TextEncoder` 先转换为 UTF-8 字节序列

## 跳过用例（实现 API 缺失）

### [SKIP-001] validateTokenPair 函数缺失（4 测试跳过）
- **涉及函数**：`validateTokenPair`
- **问题**：落地规范 §1.3 定义的 TokenPair 完整对象校验函数未导出
- **影响测试**：A01-A04（validateTokenPair 相关）
- **修复方向**：在 tokenManager.ts 中导出 `validateTokenPair` 函数，或确认该功能由 `validateTokenPairFormat` 覆盖后从契约中移除

### [SKIP-002] userStore API 不透明（7 测试跳过）
- **涉及函数**：`useSessionStore.getState()` 系列
- **问题**：测试无法确定 Zustand store 的 API（getState、setState、action 方法名）
- **影响测试**：B01, B02, B06, B07, B08, B09, A11
- **修复方向**：确认 userStore 的公开 API 与契约定义一致

### [SKIP-003] 续期/HTTP 拦截器 API 不透明（5 测试跳过）
- **涉及函数**：tokenManager.refreshTokens、httpClient 拦截器
- **问题**：测试无法确定续期和 HTTP 拦截器的精确调用方式
- **影响测试**：B04, C07, D04, D05, B03, B03-ext
- **修复方向**：需要从实现中确认续期流程的 API 与测试期望对齐

### [SKIP-004] buildMockLoginResponse 返回值不完整（2 测试跳过）
- **涉及函数**：`buildMockLoginResponse`
- **问题**：返回值缺少契约定义的字段（tokenType 等）
- **影响测试**：A19, B05
- **修复方向**：确认 mock 函数的返回结构

## 收敛状态

- 第 1 轮实现有明显缺陷：2 个已确认的实现缺陷，20 个 API 不透明导致的跳过
- 边缘函数（base64、Storage 安全封装）的防护存在遗漏
- 推荐进入 Phase 5 修复 2 个已确认的缺陷
