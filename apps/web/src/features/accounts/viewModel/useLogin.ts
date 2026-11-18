/**
 * 模块: features/accounts/viewModel/useLogin
 * 职责: 登录/注册页的视图流程控制——模式切换、密码可见性、提交文案与自动填充语义、
 *       以及提交成功后的会话写入与跳转
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 布局结构（登录/注册同屏切换）、
 *     状态覆盖表（submitting / server-error）、响应式与平台（autocomplete 语义）
 *   - docs/项目结构设计.md: MUST — 第 9 节（交互状态归 viewModel，纯视觉呈现归 view）
 * 边界:
 *   - 依赖: features/accounts/viewModel（useAuthForm、sessionStore）、react-router
 *   - 被依赖: features/accounts/view 的登录注册页
 * 禁止行为:
 *   - 禁止在本层渲染任何东西（本 hook 只出状态与回调，View 仍是唯一呈现处）
 *   - 禁止在本层调 SDK（认证端口经参数注入，提交编排仍归 useAuthForm）
 *   - 禁止在校验失败时清空输入（保留输入由 useAuthForm/useAuthFields 保证，这里不碰）
 */

import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router';

import type { AuthPort } from '../application/ports';
import type { AuthFieldName } from '../domain/formValidation';
import { useSessionStore } from './sessionStore';
import { useAuthForm, type AuthMode } from './useAuthForm';

/** 登录/注册页的成稿文案（页面设计「数据与文案」节；逐字，不在 View 里散落）。 */
export const LOGIN_COPY = {
  title: '篝火智答',
  tagline: '每一次咨询，都有据可依',
  intro: '陪你梳理照护中的困惑，找到可以迈出的下一步。',
  formTitleLogin: '登录',
  formTitleRegister: '注册账号',
  loginSubmit: '登录',
  registerSubmit: '注册',
  submittingLogin: '正在登录…',
  submittingRegister: '正在注册…',
  toRegister: '已有邀请码？注册账号',
  toLogin: '已有账号？返回登录',
  passwordShow: '显示密码',
  passwordHide: '隐藏密码',
  inviteHint: '邀请码由运营者发放，8 位、一次性使用',
  accountHint: '账号名不需要是邮箱',
  resetNote: '忘记密码？请联系运营者人工重置',
  // 登录页的安全与用途说明（可扫读的一句告知；详单仍归设置页/使用说明页）。
  notice: '咨询内容会发送给模型服务处理后返回；本应用不能替代专业服务。',
} as const;

/** useLogin 的返回形状（View 只依赖这些）。 */
export interface LoginController {
  /** 当前模式：登录或注册。 */
  mode: AuthMode;
  /** 表单控制器（值/错误/提交中/服务端错误/提交动作）。 */
  form: ReturnType<typeof useAuthForm>;
  /** 是否以明文展示密码。 */
  showPassword: boolean;
  /** 当前模式的主按钮文字。 */
  submitLabel: string;
  /** 当前模式的提交中文案。 */
  pendingLabel: string;
  /** 切换到另一种模式（登录↔注册）。 */
  toggleMode(): void;
  /** 切换密码可见性。 */
  togglePasswordVisibility(): void;
  /** 按字段给出输入框的 autocomplete 语义（原生自动填充）。 */
  autocompleteFor(field: AuthFieldName): string;
}

/**
 * 登录/注册页视图流程控制器。
 *
 * @param auth 认证端口（组合根注入；测试传替身）。
 * @param initialMode 初始模式；默认登录（登录页是每个使用者的第一屏）。
 *
 * 为什么把模式切换、密码可见性与文案从 View 挪到这里：它们是「登录/注册」这一交互
 * 关注点，而不是某一个字段的视觉细节；集中一处后 View 只剩结构与类名，模式相关文案
 * 也不再散落在 JSX 的每个三元里。提交编排与校验仍由 useAuthForm/useAuthFields 承担，
 * 本 hook 不重复实现，也不改变它们的行为。
 */
export function useLogin(auth: AuthPort, initialMode: AuthMode = 'login'): LoginController {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [showPassword, setShowPassword] = useState(false);
  const navigate = useNavigate();
  const markAuthenticated = useSessionStore((state) => state.markAuthenticated);

  const form = useAuthForm(mode, auth, (account) => {
    // 提交响应即证明会话已签发：写入本地记录并转首页，不再多查一轮（同原 LoginPage 注释）。
    markAuthenticated(account);
    void navigate('/', { replace: true });
  });

  /**
   * 自动填充语义（页面设计「响应式与平台」节）。
   *
   * 账号名为 `username`；密码在注册态用 `new-password`（浏览器据此提供强密码建议而不会
   * 回填旧密码），登录态用 `current-password`。
   */
  const autocompleteFor = useCallback(
    (field: AuthFieldName): string => {
      if (field === 'account') return 'username';
      if (field === 'password') return mode === 'register' ? 'new-password' : 'current-password';
      return 'off';
    },
    [mode],
  );

  return {
    mode,
    form,
    showPassword,
    submitLabel: mode === 'login' ? LOGIN_COPY.loginSubmit : LOGIN_COPY.registerSubmit,
    pendingLabel: mode === 'login' ? LOGIN_COPY.submittingLogin : LOGIN_COPY.submittingRegister,
    toggleMode: () => setMode((current) => (current === 'login' ? 'register' : 'login')),
    togglePasswordVisibility: () => setShowPassword((current) => !current),
    autocompleteFor,
  };
}
