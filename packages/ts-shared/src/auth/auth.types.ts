/**
 * 模块: @campfire/ts-shared.auth.types
 * 职责: 认证域前端接口类型——注册/登录/Token/me/准入审核/邀请码管理 DTO。
 *       与后端 py-schemas.auth 的 Pydantic 模型字段逐一对应。
 * 数据来源:
 *   - py-schemas (auth): MUST — 后端 Pydantic 模型（py_schemas.auth）
 * 边界:
 *   - 依赖: auth.enums.ts
 *   - 被依赖: react-web auth 特性（domain/application 层）
 * 禁止行为:
 *   - 禁止包含运行时业务逻辑——纯类型定义
 *   - 禁止出现 username / device_id 字段（已随匿名演示轨废除）
 */

import type { AccountStatus, InviteChannel, InviteCodeStatus, UserRole } from './auth.enums';
import type { ISODateTime } from '../common/common.types';

// === 注册 / 登录 / Token ===

/** 用户注册请求体——对应后端 RegisterRequest */
export interface RegisterRequest {
  phone: string;
  password: string;
  invite_code: string;
  role: UserRole;
  real_name?: string | null;
}

/** 用户注册成功响应体——对应后端 RegisterResponse */
export interface RegisterResponse {
  result: 'success';
  user_id: string;
  status: AccountStatus;
  message: string;
}

/** 登录请求体（手机号 + 密码）——对应后端 LoginRequest */
export interface LoginRequest {
  phone: string;
  password: string;
}

/** 认证令牌响应体——对应后端 TokenResponse */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: 'Bearer';
}

/** 续期请求体——对应后端 RefreshRequest */
export interface RefreshRequest {
  refresh_token: string;
}

/** 当前用户信息响应——对应后端 MeResponse */
export interface MeResponse {
  user_id: string;
  phone: string;
  real_name: string | null;
  role: UserRole;
  status: AccountStatus;
  reject_reason: string | null;
}

// === 准入审核（admin） ===

/** 准入审核列表项——对应后端 ReviewListItem */
export interface ReviewListItem {
  user_id: string;
  phone: string;
  real_name: string | null;
  role: UserRole;
  status: AccountStatus;
  reject_reason: string | null;
  created_at: ISODateTime;
}

/** 准入审核列表响应——对应后端 ReviewListResponse */
export interface ReviewListResponse {
  items: ReviewListItem[];
  total: number;
}

/** 审核通过响应——对应后端 ReviewApproveResponse */
export interface ReviewApproveResponse {
  user_id: string;
  status: AccountStatus;
  message: string;
}

/** 审核驳回请求——对应后端 ReviewRejectRequest */
export interface ReviewRejectRequest {
  reason: string;
}

/** 驳回后补交材料重提请求——对应后端 ReviewResubmitRequest */
export interface ReviewResubmitRequest {
  real_name?: string | null;
}

// === 邀请码管理（admin） ===

/** 邀请码生成请求——对应后端 InviteCodeCreateRequest */
export interface InviteCodeCreateRequest {
  channel: InviteChannel;
  max_uses?: number;
  count?: number;
  expires_at: ISODateTime;
}

/** 邀请码生成响应——对应后端 InviteCodeCreateResponse */
export interface InviteCodeCreateResponse {
  codes: string[];
}

/** 邀请码列表项——对应后端 InviteCodeItem */
export interface InviteCodeItem {
  code: string;
  channel: InviteChannel;
  max_uses: number;
  used_count: number;
  expires_at: ISODateTime;
  status: InviteCodeStatus;
  created_by: string;
  created_at: ISODateTime;
}

/** 邀请码列表响应——对应后端 InviteCodeListResponse */
export interface InviteCodeListResponse {
  items: InviteCodeItem[];
  total: number;
}
