/**
 * 模块: features/accounts/viewModel/useAuthFields
 * 职责: 表单字段值的状态机——touched/errors 的迁移与即时重校验
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 状态覆盖表（untouched / invalid-after-touched）
 *   - docs/项目结构设计.md: MUST — 第 9 节（状态归属三分：跨组件交互状态归 viewModel）
 * 边界:
 *   - 依赖: features/accounts/domain/formValidation（纯校验规则）
 *   - 被依赖: features/accounts/viewModel/useAuthForm
 * 禁止行为:
 *   - 禁止在本层调端口或用例（提交编排归 useAuthForm）
 *   - 禁止在校验失败时清空字段值（保留输入是状态覆盖表的要求）
 */

import { useRef, useState } from 'react';

import type { AuthFieldName, FieldErrors } from '../domain/formValidation';
import { validateLoginForm, validateRegisterForm } from '../domain/formValidation';
import type { AuthMode } from './useAuthForm';

/** 表单字段值的形状；两种模式共用（登录时 inviteCode 恒为空串）。 */
export interface AuthFormValues {
  account: string;
  password: string;
  inviteCode: string;
}

const EMPTY_VALUES: AuthFormValues = { account: '', password: '', inviteCode: '' };

/** 字段值状态机的返回形状。 */
export interface AuthFieldsController {
  /** 当前表单值（不可变；View 不得就地修改）。 */
  values: AuthFormValues;
  /** 按字段归集的校验错误（含未触碰字段的错误，是否呈现由 View 按 touched 决定）。 */
  errors: FieldErrors;
  /** 已触碰（blur 过）的字段集合；untouched 态不显示任何红色。 */
  touched: ReadonlySet<AuthFieldName>;
  /** 字段变更：更新值，并对已触碰字段即时重校验。 */
  setField(field: AuthFieldName, value: string): void;
  /** 字段失焦：标记 touched 并立即校验。 */
  blurField(field: AuthFieldName): void;
  /** 用给定错误集合替换当前错误，并把对应字段标为已触碰。 */
  applyErrors(errors: FieldErrors): void;
}

/** 一次校验：按模式选规则，返回字段错误（空对象表示通过）。 */
function validate(mode: AuthMode, values: AuthFormValues): FieldErrors {
  return mode === 'login'
    ? validateLoginForm({ account: values.account, password: values.password })
    : validateRegisterForm(values);
}

/**
 * 管理登录/注册表单的字段状态。
 *
 * @param mode 表单模式；决定用哪套校验规则。
 *
 * 为什么单独成 hook 而不是与提交逻辑写在一起：字段状态机（值/touched/错误三者的
 * 一致性）与提交编排（闸门、用例、服务端错误）是两个独立的关注点，混在一个 hook 里
 * 会让两者的状态互相牵制，且函数的嵌套与分支数同时上升。
 */
export function useAuthFields(mode: AuthMode): AuthFieldsController {
  const [values, setValues] = useState<AuthFormValues>(EMPTY_VALUES);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [touched, setTouched] = useState<ReadonlySet<AuthFieldName>>(() => new Set());

  // touched 的镜像：setField 需要在同一次事件里读到最新集合决定是否即时校验，
  // 而 state 的更新要到下次渲染才可见。镜像只在事件处理函数里读写，不与渲染竞争。
  const touchedRef = useRef<ReadonlySet<AuthFieldName>>(new Set());

  const applyTouched = (next: ReadonlySet<AuthFieldName>): void => {
    touchedRef.current = next;
    setTouched(next);
  };

  return {
    values,
    errors,
    touched,
    setField(field, value) {
      const nextValues = { ...values, [field]: value };
      setValues(nextValues);
      if (touchedRef.current.has(field)) {
        setErrors(validate(mode, nextValues));
      }
    },
    blurField(field) {
      applyTouched(new Set(touchedRef.current).add(field));
      setErrors(validate(mode, values));
    },
    applyErrors(nextErrors) {
      const nextTouched = new Set(touchedRef.current);
      for (const field of Object.keys(nextErrors) as AuthFieldName[]) nextTouched.add(field);
      applyTouched(nextTouched);
      setErrors(nextErrors);
    },
  };
}
