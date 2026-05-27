## 测试缺陷报告（第 1 轮）

#### [缺陷-001] mockInterceptors 初始化时序错误
- **契约条款**：§N/A（测试基础设施bug）
- **缺陷类型**：运行时错误（ReferenceError: Cannot access 'mockInterceptors' before initialization）
- **期望行为**：httpClient.ts 在模块级调用 `registerInterceptor()`，测试的 `vi.mock` mock 工厂函数应能正确处理模块级副作用
- **修复方向**：将 `mockInterceptors` 数组的声明移动到 `vi.mock()` 调用之前，或使用 `vi.hoisted()` 提升变量。同时考虑在 `vi.mock` 的工厂函数内部定义 `mockInterceptors` 以避免作用域问题。
- **根因**：httpClient.ts 在文件顶层调用 `Taro.addInterceptor()`（模块级副作用），vitest 的 `vi.mock` 工厂函数在模块导入时被调用，此时 `mockInterceptors` 变量尚未初始化。
