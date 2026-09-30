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

  // values 与 touched 的镜像：state 的更新要到下次渲染才可见，而同一任务内的连续事件
  // （浏览器自动填充/密码管理器会一次填多个字段）必须在闭包之外读到「含本次写入」的最新值。
  // 镜像只在事件处理函数里读写，不与渲染竞争；写入点与 setValues 同处，不另开路径。
  const valuesRef = useRef<AuthFormValues>(EMPTY_VALUES);
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
      // 函数式更新：同一任务内连续两次 setField 各自基于前一次的结果。
      // 若写成 `{ ...values, [field]: value }`（闭包旧值），两次更新落在同一批次时
      // 第二次会把第一次的字段值覆盖掉——字段被静默清空（同批次两次写入的守卫见 useAuthFields.test）。
      setValues((prev) => ({ ...prev, [field]: value }));
      // 即时重校验要读含本次写入的最新值；函数式更新的新值在 updater 外拿不到，
      // 故用与 state 同步的镜像算出同一份新值。
      const nextValues = { ...valuesRef.current, [field]: value };
      valuesRef.current = nextValues;
      if (touchedRef.current.has(field)) {
        setErrors(validate(mode, nextValues));
      }
    },
    blurField(field) {
      applyTouched(new Set(touchedRef.current).add(field));
      // 读镜像而不是闭包里的 values：同一任务内「写入 → 失焦」时闭包值还是旧的，
      // 会把刚填好的字段误判成空（与 setField 同一类陈旧读）。
      setErrors(validate(mode, valuesRef.current));
    },
    applyErrors(nextErrors) {
      const nextTouched = new Set(touchedRef.current);
      for (const field of Object.keys(nextErrors) as AuthFieldName[]) nextTouched.add(field);
      applyTouched(nextTouched);
      setErrors(nextErrors);
    },
  };
}
