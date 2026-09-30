/**
 * 模块: features/accounts/viewModel/useAuthForm
 * 职责: 登录/注册表单的提交编排——并发闸门、用例调用与服务端错误态
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 状态覆盖表（submitting / server-error / 限流触发）
 *   - docs/项目结构设计.md: MUST — 第 9 节（组件内视觉状态归 view，交互状态归 viewModel）
 * 边界:
 *   - 依赖: features/accounts/domain、application、viewModel/useAuthFields
 *   - 被依赖: features/accounts/view 的登录注册页
 * 禁止行为:
 *   - 禁止在 hook 里直接调 SDK（端口经参数注入，测试用替身）
 *   - 禁止用 `disabled` 当并发闸门（闸门收进动作函数体，FE-12）
 *   - 禁止在提交失败时清空已输入内容（页面设计 server-error 行）
 */

import { useRef, useState } from 'react';

import { AUTH_FAILURE_MESSAGES, AuthError, type AuthFailureKind } from '../domain/authFailure';
import { ValidationError } from '../domain/formValidation';
import { SubmitLoginUseCase, SubmitRegisterUseCase } from '../application/usecases';
import type { AuthPort } from '../application/ports';
import type { AuthenticatedAccount } from '../domain/session';
import { useAuthFields, type AuthFormValues } from './useAuthFields';

/** 表单模式。 */
export type AuthMode = 'login' | 'register';

export type { AuthFormValues } from './useAuthFields';

/** 服务端错误（表单级横幅）：分类 + 逐字文案。 */
export interface ServerError {
  kind: AuthFailureKind;
  message: string;
}

/** useAuthForm 的返回形状（View 只依赖这些）。 */
export interface AuthFormController {
  /** 当前表单值（不可变；View 不得就地修改）。 */
  values: AuthFormValues;
  /** 按字段归集的校验错误（是否呈现由 View 按 touched 决定）。 */
  errors: Partial<Record<'account' | 'password' | 'inviteCode', string>>;
  /** 已触碰（blur 过）的字段集合；untouched 态不显示任何红色。 */
  touched: ReadonlySet<'account' | 'password' | 'inviteCode'>;
  /** 是否正在提交（提交中字段锁定、按钮进入 loading）。 */
  submitting: boolean;
  /** 服务端拒绝：null 表示无（页面设计 server-error / 限流两行的容器）。 */
  serverError: ServerError | null;
  /** 用户是否改过任一字段；用于「保留已输入内容」的降级呈现。 */
  dirty: boolean;
  /** 字段变更：更新值，并对已触碰字段即时重校验。 */
  setField(field: 'account' | 'password' | 'inviteCode', value: string): void;
  /** 字段失焦：标记 touched 并立即校验。 */
  blurField(field: 'account' | 'password' | 'inviteCode'): void;
  /** 提交表单；校验或被拒时返回 false，View 据此决定是否导航。 */
  submit(): Promise<boolean>;
}

/** 按模式调用对应用例。返回账号名或抛出用例的异常。 */
function runUseCase(mode: AuthMode, auth: AuthPort, values: AuthFormValues): Promise<AuthenticatedAccount> {
  return mode === 'login'
    ? new SubmitLoginUseCase(auth).execute({ account: values.account, password: values.password })
    : new SubmitRegisterUseCase(auth).execute(values);
}

/**
 * 登录/注册表单控制器。
 *
 * @param mode 表单模式；登录态无邀请码字段（页面设计布局结构节）。
 * @param auth 认证端口（组合根注入；测试传替身）。
 * @param onAuthenticated 提交成功后的回调，接收端口回带的账号名。
 */
export function useAuthForm(
  mode: AuthMode,
  auth: AuthPort,
  onAuthenticated: (account: AuthenticatedAccount) => void,
): AuthFormController {
  const fields = useAuthFields(mode);
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<ServerError | null>(null);
  // 并发闸门收进动作函数体（FE-12）：`disabled` 管不住 Enter 键与程序化调用，
  // 而 ref 的写入是同步的，能在同一次事件循环里挡住重复提交。
  const inFlight = useRef(false);

  /** 把异常转成 UI 状态；返回 false 表示本次提交未成功。 */
  const applyFailure = (error: unknown): false => {
    if (error instanceof ValidationError) {
      // 校验拒绝不改动已输入内容，只把错误落到全部字段上（提交是一次全量校验）。
      fields.applyErrors(error.fieldErrors);
      return false;
    }
    // server-error：横幅呈现原因，输入内容保留（页面设计状态覆盖表）。
    // 非端口契约内的抛出物也走这里（CORE-07：不静默吞掉），用通用文案呈现。
    setServerError(
      error instanceof AuthError
        ? { kind: error.kind, message: error.message }
        : { kind: 'unexpected', message: AUTH_FAILURE_MESSAGES.unexpected },
    );
    return false;
  };

  // 刻意不用 useCallback：这些函数只被本组件的 onSubmit/onChange 直接调用，
  // 没有以它们为依赖的 memo 子树；包一层 useCallback 只会引入一处需要维护的依赖数组。
  return {
    values: fields.values,
    errors: fields.errors,
    touched: fields.touched,
    submitting,
    serverError,
    dirty: fields.values.account !== '' || fields.values.password !== '' || fields.values.inviteCode !== '',
    setField: fields.setField,
    blurField: fields.blurField,
    submit: async (): Promise<boolean> => {
      // 闸门在函数体内：重复提交在这里被拒绝，不依赖按钮是否 disabled。
      if (inFlight.current) return false;
      inFlight.current = true;
      setSubmitting(true);
      setServerError(null);
      try {
        onAuthenticated(await runUseCase(mode, auth, fields.values));
        return true;
      } catch (error) {
        return applyFailure(error);
      } finally {
        inFlight.current = false;
        setSubmitting(false);
      }
    },
  };
}
