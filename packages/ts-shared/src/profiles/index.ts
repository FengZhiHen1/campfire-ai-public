/**
 * @campfire/ts-shared/profiles — 档案管理域共享类型、枚举与契约。
 *
 * 提供 N 大能力：
 * 1. 枚举定义：DiagnosisType、LanguageLevel、SensoryFeature 等 6 个前端枚举
 * 2. 接口类型：ProfileCreate、ProfileResponse、EventCreate、EventResponse 等 CRUD DTO
 * 3. 品牌类型：ProfileId、EventId、CaregiverId
 * 4. 类型守卫：isValidProfileCreate、isValidEventCreate 等运行时校验
 *
 * Usage:
 *     import { ProfileCreate, ProfileListItem, isValidProfileCreate } from '@campfire/ts-shared/profiles';
 */

export * from './profiles.enums';
export * from './profiles.types';
export * from './profiles.contract';
