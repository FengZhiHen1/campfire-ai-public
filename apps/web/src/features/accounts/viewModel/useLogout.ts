/**
 * 模块: features/accounts/viewModel/useLogout
 * 职责: 登出流程的交互状态——确认单开关、提交中、失败内联错误与重试
 * 数据来源:
 *   - docs/design/pages/设置页.md: MUST — 状态覆盖表（退出登录 submitting / 登出失败 / 会话过期 401）
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 6 节（登出经 SDK signOut，随后清状态回登录页）
 * 边界:
 *   - 依赖: features/accounts/application（LogoutUseCase）、domain（AuthError）
 *   - 被依赖: features/accounts/view 的设置页
 * 禁止行为:
 *   - 禁止在登出失败时关闭确认单（保留操作上下文，设置页状态覆盖表）
 *   - 禁止在登出失败时清本地会话（清状态等于假装已登出，此时服务端会话可能仍有效）
 */

import { useCallback, useRef, useState } from 'react';

import { AuthError } from '../domain/authFailure';
import { LogoutUseCase } from '../application/usecases';
import type { AuthPort } from '../application/ports';

/** useLogout 的返回形状。 */
export interface LogoutController {
  /** 确认单是否打开。 */
  confirming: boolean;
  /** 是否正在执行登出。 */
  submitting: boolean;
  /** 登出失败的原因；null 表示无错误。 */
  error: string | null;
  /** 打开确认单（键盘与程序化调用都走它）。 */
  open(): void;
  /** 关闭确认单并清掉上一次的错误。 */
  close(): void;
  /** 执行登出；成功返回 true（调用方据此跳登录页）。 */
  confirm(): Promise<boolean>;
}

/**
 * 登出控制器。
 *
 * @param auth 认证端口（组合根注入）。
 * @param onLoggedOut 登出成功后的回调（清本地会话状态）。
 */
export function useLogout(auth: AuthPort, onLoggedOut: () => void): LogoutController {
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 并发闸门在动作函数体内（FE-12）：sheet 里的按钮 disabled 管不住回车与重复点按。
  const inFlight = useRef(false);

  const open = useCallback(() => {
    setError(null);
    setConfirming(true);
  }, []);

  const close = useCallback(() => {
    // 登出失败时 sheet 不自动关闭（状态覆盖表），close 只由使用者主动触发。
    setConfirming(false);
    setError(null);
  }, []);

  const confirm = useCallback(async (): Promise<boolean> => {
    if (inFlight.current) return false;
    inFlight.current = true;
    setSubmitting(true);
    setError(null);
    try {
      await new LogoutUseCase(auth).execute();
      onLoggedOut();
      setConfirming(false);
      return true;
    } catch (caught) {
      // 失败留在 sheet 内呈现并允许重试（状态覆盖表）；不清本地状态。
      setError(caught instanceof AuthError ? caught.message : '退出没有成功，请稍后重试');
      return false;
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }, [auth, onLoggedOut]);

  return { confirming, submitting, error, open, close, confirm };
}
