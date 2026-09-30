/**
 * 模块: features/accounts/viewModel/useAuthForm
 * 职责: 登录/注册表单的交互状态——touched/dirty、字段错误、提交中与服务端错误
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 状态覆盖表（untouched / invalid-after-touched / submitting / server-error / 限流）
 *   - docs/项目结构设计.md: MUST — 第 9 节（状态归属三分：组件内视觉状态归 view，交互状态归 viewModel）
 * 边界:
 *   - 依赖: features/accounts/domain 与 application
 *   - 被依赖: features/accounts/view 的登录注册页
 * 禁止行为:
 *   - 禁止在 hook 里直接调 SDK（端口经参数注入，测试用替身）
 *   - 禁止用 `disabled` 当并发闸门（闸门收进动作函数体，FE-12）
 *   - 禁止在提交失败时清空已输入内容（页面设计 server-error 行）
 */

import { useCallback, useRef, useState } from 'react';

import { AuthError, type AuthFailureKind } from '../domain/authFailure';
import type { AuthFieldName, FieldErrors } from '../domain/formValidation';
import { ValidationError, validateLoginForm, validateRegisterForm } from '../domain/formValidation';
import { SubmitLoginUseCase, SubmitRegisterUseCase } from '../application/usecases';
import type { AuthPort } from '../application/ports';
import type { AuthenticatedAccount } from '../domain/session';

/** 表单模式。 */
export type AuthMode = 'login' | 'register';

/** 表单字段值的形状；两种模式共用（登录时 inviteCode 恒为空串）。 */
export interface AuthFormValues {
  account: string;
  password: string;
  inviteCode: string;
}

const EMPTY_VALUES: AuthFormValues = { account: '', password: '', inviteCode: '' };

/** 服务端错误（表单级横幅）：分类 + 逐字文案。 */
export interface ServerError {
  kind: AuthFailureKind;
  message: string;
}

/** useAuthForm 的返回形状（View 只依赖这些）。 */
export interface AuthFormController {
  /** 当前表单值（不可变；View 不得就地修改）。 */
  values: AuthFormValues;
  /** 按字段归集的校验错误（含未触碰字段的错误，是否呈现由 View 按 touched 决定）。 */
  errors: FieldErrors;
  /** 已触碰（blur 过）的字段集合；untouched 态不显示任何红色（craft form-validation）。 */
  touched: ReadonlySet<AuthFieldName>;
  /** 是否正在提交（提交中字段锁定、按钮进入 loading）。 */
  submitting: boolean;
  /** 服务端拒绝：null 表示无（页面设计 server-error / 限流两行的容器）。 */
  serverError: ServerError | null;
  /** 用户是否改过任一字段；用于「保留已输入内容」的降级呈现。 */
  dirty: boolean;
  /** 字段变更：更新值，并对已触碰字段即时重校验（invalid 后按 input 恢复校验）。 */
  setField(field: AuthFieldName, value: string): void;
  /** 字段失焦：标记 touched 并立即校验。 */
  blurField(field: AuthFieldName): void;
  /** 提交表单；校验或被拒时返回 false，View 据此决定是否导航。 */
  submit(): Promise<boolean>;
}

/** 一次校验：按模式选规则，返回字段错误（空对象表示通过）。 */
function validate(mode: AuthMode, values: AuthFormValues): FieldErrors {
  return mode === 'login'
    ? validateLoginForm({ account: values.account, password: values.password })
    : validateRegisterForm(values);
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
  const [values, setValues] = useState<AuthFormValues>(EMPTY_VALUES);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [touched, setTouched] = useState<ReadonlySet<AuthFieldName>>(() => new Set());
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<ServerError | null>(null);

  // touched 的镜像：setField 需要在同一次事件里读到最新集合决定是否即时校验，
  // 而 state 的更新要到下次渲染才可见。镜像只在事件处理函数里读写，不与渲染竞争。
  const touchedRef = useRef<ReadonlySet<AuthFieldName>>(new Set());
  // 并发闸门收进动作函数体（FE-12）：`disabled` 管不住 Enter 键与程序化调用，
  // 而 ref 的写入是同步的，能在同一次事件循环里挡住重复提交。
  const inFlight = useRef(false);

  const setField = useCallback(
    (field: AuthFieldName, value: string) => {
      const nextValues = { ...values, [field]: value };
      setValues(nextValues);
      if (touchedRef.current.has(field)) {
        setErrors(validate(mode, nextValues));
      }
    },
    [mode, values],
  );

  const blurField = useCallback(
    (field: AuthFieldName) => {
      const nextTouched = new Set(touchedRef.current).add(field);
      touchedRef.current = nextTouched;
      setTouched(nextTouched);
      setErrors(validate(mode, values));
    },
    [mode, values],
  );

  const submit = useCallback(async (): Promise<boolean> => {
    // 闸门在函数体内：重复提交在这里被拒绝，不依赖按钮是否 disabled。
    if (inFlight.current) return false;
    inFlight.current = true;
    setSubmitting(true);
    setServerError(null);
    try {
      const account =
        mode === 'login'
          ? await new SubmitLoginUseCase(auth).execute({ account: values.account, password: values.password })
          : await new SubmitRegisterUseCase(auth).execute(values);
      onAuthenticated(account);
      return true;
    } catch (error) {
      if (error instanceof ValidationError) {
        // 校验拒绝不改动已输入内容，只把错误落到全部字段上（提交是一次全量校验）。
        const failed = Object.keys(error.fieldErrors) as AuthFieldName[];
        const nextTouched = new Set(touchedRef.current);
        for (const field of failed) nextTouched.add(field);
        touchedRef.current = nextTouched;
        setTouched(nextTouched);
        setErrors(error.fieldErrors);
        return false;
      }
      if (error instanceof AuthError) {
        // server-error：横幅呈现原因，输入内容保留（页面设计状态覆盖表）。
        setServerError({ kind: error.kind, message: error.message });
        return false;
      }
      // 非端口契约内的抛出物：不静默吞掉（CORE-07），转成表单级错误呈现。
      setServerError({ kind: 'unexpected', message: '操作没有成功，请稍后重试' });
      return false;
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }, [auth, mode, onAuthenticated, values]);

  return {
    values,
    errors,
    touched,
    submitting,
    serverError,
    dirty: values.account !== '' || values.password !== '' || values.inviteCode !== '',
    setField,
    blurField,
    submit,
  };
}
