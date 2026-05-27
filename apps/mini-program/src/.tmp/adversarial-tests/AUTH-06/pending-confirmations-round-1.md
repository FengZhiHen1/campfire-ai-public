# pending-confirmations-round-1.md

> Round 1 缺陷修复确认记录
> 生成时间: 2026-05-27
> 模块: AUTH-06 认证会话管理

## 修复状态

### 缺陷 1: safeSetStorage 循环引用处理

- **状态**: 已修复
- **文件**: `apps/mini-program/src/logics/shared/utils/storage.ts`
- **修复内容**: 将 `JSON.stringify(data)` 移入 try-catch 块内，包括初次写入和容量超限重试路径。当 `data` 为循环引用对象时，`JSON.stringify` 抛出的 `TypeError: Converting circular structure to JSON` 被 catch 捕获，函数返回 `false` 而非向上抛出异常。
- **变更行**: 原第 63 行的 `JSON.stringify(data)` 调用从 try-catch 外部移至 try 块首行（现第 64 行）；重试路径同样在 try-catch 内执行 `JSON.stringify(data)`（现第 73 行）。

### 缺陷 2: base64UrlEncode 中文多字节字符编码

- **状态**: 已修复
- **文件**: `apps/mini-program/src/logics/shared/utils/storage.ts`
- **修复内容**:
  - `base64UrlEncode`: 在编码前使用 `encodeURIComponent` + 正则替换将字符串转为 UTF-8 字节序列，再对字节序列执行 base64 编码。确保中文等多字节 UTF-8 字符可逆编解码。
  - `base64UrlDecode`: 解码后将字节序列通过 `percent-encoding` + `decodeURIComponent` 还原为原始 UTF-8 字符串，保持与编码对称。增加 `decodeURIComponent` 的 try-catch 保护，解码失败时回退为按字节构建原始字符串。
- **变更行**:
  - `base64UrlDecode`（第 161-207 行）：内部改为收集字节数组 + percent-encoded UTF-8 还原
  - `base64UrlEncode`（第 218-246 行）：增加 encodeURIComponent 预处理步骤

## 契约一致性检查

- 所有修复均未改变对外接口签名
- `safeSetStorage` 返回值类型仍为 `boolean`
- `base64UrlEncode` 返回值类型仍为 `string`，输入参数签名不变
- 未引入契约文件中未声明的新字段
- 对 ASCII 输入（如标准 JWT token）的行为完全向后兼容

## 待验证

修复由 adversarial-test-generator 在 Round 2 中重新运行对抗性测试验证。
