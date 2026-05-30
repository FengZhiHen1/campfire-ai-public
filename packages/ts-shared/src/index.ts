/**
 * @campfire/ts-shared — 前端共享类型、枚举与契约。
 *
 * L2 共享能力层——提供跨 mini-program 复用的纯类型定义与校验工具。
 * 与后端 py-schemas 对齐，作为前后端数据契约的前端镜像。
 *
 * 提供三大域：
 * 1. cases/   — 案例管理域（枚举、接口类型、品牌类型、类型守卫）
 * 2. profiles/ — 档案管理域（枚举、接口类型、品牌类型、类型守卫）
 * 3. common/  — 跨域共享（泛型分页、API 错误结构、工具类型、通用校验）
 *
 * 核心原则：
 *   - 仅包含纯类型和枚举，不含运行时业务逻辑
 *   - 品牌类型（Branded Types）防止语义混淆
 *   - 类型守卫提供运行时数据校验
 *   - 所有类型与后端 py-schemas 对齐
 *
 * Usage:
 *     // 按域导入
 *     import { CaseStatus, CaseCreateRequest, CaseId } from '@campfire/ts-shared/cases';
 *     import { ProfileCreate, DiagnosisType } from '@campfire/ts-shared/profiles';
 *     import { PaginatedResponse, isISODateTime } from '@campfire/ts-shared/common';
 */

export * from './cases';
export * from './profiles';
export * from './common';
