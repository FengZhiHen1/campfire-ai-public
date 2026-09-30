/**
 * 模块: features/accounts/view/LoginPage
 * 职责: 登录与注册页——品牌区、表单区（账号名/密码/邀请码）、底部互切行与状态呈现
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 全文（布局结构、组件选用、数据与文案、状态覆盖、动效意图）
 *   - docs/design/components.html: MUST — .panel/.field/.field-error 的类名与结构
 * 边界:
 *   - 依赖: features/accounts/viewModel/useAuthForm、shared/ui、react-router
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止在本层调用 SDK 或任何 HTTP（端口由 app 装配注入）
 *   - 禁止渲染邮箱字段或找回密码入口（AC-16 的界面侧：一期无邮箱）
 *   - 禁止在提交失败时清空输入（状态保留由 viewModel 保证，View 不得另行重置）
 */

import { useState } from 'react';
import { useNavigate } from 'react-router';

import { BrandMark } from '../../../shared/ui/BrandMark';
import { ErrorCard } from '../../../shared/ui/StatePrimitives';
import type { AuthPort } from '../application/ports';
import type { AuthFieldName } from '../domain/formValidation';
import { useSessionStore } from '../viewModel/sessionStore';
import { useAuthForm, type AuthMode } from '../viewModel/useAuthForm';
import styles from './loginPage.module.css';

/** 登录页 props：认证端口经 props 注入（组合根在 app 层）。 */
export interface LoginPageProps {
  /** 认证端口（可能是 SDK 实现或测试替身）。 */
  auth: AuthPort;
  /** 初始模式；默认登录（页面设计：登录页是每个使用者的第一屏）。 */
  initialMode?: AuthMode;
}

/** 页面文案（页面设计「布局结构」与「数据与文案」节的成稿）。 */
const COPY = {
  title: '篝火智答',
  tagline: '每一次咨询，都有据可依',
  loginSubmit: '登录',
  registerSubmit: '注册',
  submittingLogin: '正在登录…',
  submittingRegister: '正在注册…',
  toRegister: '已有邀请码？注册账号',
  toLogin: '已有账号？返回登录',
  passwordShow: '显示密码',
  passwordHide: '隐藏密码',
  inviteHint: '邀请码由运营者发放，8 位、一次性使用',
  manualReset: '忘记密码？请联系运营者人工重置。',
} as const;

/**
 * 自动填充语义（页面设计「响应式与平台」节：原生 autocomplete）。
 *
 * 账号名用 `username`：它是登录标识；密码在注册态用 `new-password`（浏览器据此
 * 提供强密码建议而不会回填旧密码），登录态用 `current-password`。
 */
function autocompleteFor(field: AuthFieldName, mode: AuthMode): string {
  if (field === 'account') return 'username';
  if (field === 'password') return mode === 'register' ? 'new-password' : 'current-password';
  return 'off';
}

/**
 * 渲染登录/注册页。
 *
 * 前置: 认证端口已装配（SDK init 由 app 层负责）
 * 后置: 提交成功后写入会话 store 并转首页；失败时保留输入并呈现错误
 * 异常: 无（端口异常已由 viewModel 转成服务端错误态）
 *
 * 为什么提交成功后直接导航而不等会话查证：登录响应本身就证明会话已签发，
 * 再查一次只多一轮往返与一次闪烁；markAuthenticated 是同一事实的本地记录。
 */
export function LoginPage({ auth, initialMode = 'login' }: LoginPageProps) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [showPassword, setShowPassword] = useState(false);
  const navigate = useNavigate();
  const markAuthenticated = useSessionStore((state) => state.markAuthenticated);

  const form = useAuthForm(mode, auth, (account) => {
    markAuthenticated(account);
    void navigate('/', { replace: true });
  });

  const submitLabel = mode === 'login' ? COPY.loginSubmit : COPY.registerSubmit;
  const pendingLabel = mode === 'login' ? COPY.submittingLogin : COPY.submittingRegister;

  /** 字段错误只在已触碰时呈现（untouched 态无红色，craft form-validation）。 */
  const errorFor = (field: AuthFieldName): string | undefined =>
    form.touched.has(field) ? form.errors[field] : undefined;

  return (
    <div className={`phone-shell ${styles.shell}`}>
      <section className={styles.brand} aria-labelledby="auth-title">
        <div className={styles.brandRow}>
          <span className={styles.brandMark}>
            <BrandMark size="1.2em" />
          </span>
          <h1 className={styles.title} id="auth-title">
            {COPY.title}
          </h1>
        </div>
        <p className={styles.tagline}>{COPY.tagline}</p>
      </section>

      <section className={`panel ${styles.panel}`} aria-labelledby="auth-form-title">
        <h2 className={styles.formTitle} id="auth-form-title">
          {mode === 'login' ? '登录' : '注册账号'}
        </h2>

        {/* server-error 与限流共用这一个横幅位置（页面设计状态覆盖表两行同形态）。 */}
        {form.serverError !== null && (
          <ErrorCard
            title={form.serverError.kind === 'rate-limited' ? '暂时无法继续' : '没有成功'}
            description={form.serverError.message}
          />
        )}

        <form
          className={styles.form}
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void form.submit();
          }}
        >
          <div className="field">
            <label htmlFor="auth-account">账号名</label>
            <input
              id="auth-account"
              name="account"
              type="text"
              autoComplete={autocompleteFor('account', mode)}
              value={form.values.account}
              disabled={form.submitting}
              aria-invalid={errorFor('account') !== undefined}
              aria-describedby={errorFor('account') === undefined ? undefined : 'auth-account-error'}
              onChange={(event) => form.setField('account', event.target.value)}
              onBlur={() => form.blurField('account')}
            />
            <span className="field-error" id="auth-account-error" role="alert">
              {errorFor('account')}
            </span>
          </div>

          <div className="field">
            <label htmlFor="auth-password">密码</label>
            <input
              id="auth-password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete={autocompleteFor('password', mode)}
              value={form.values.password}
              disabled={form.submitting}
              aria-invalid={errorFor('password') !== undefined}
              aria-describedby={errorFor('password') === undefined ? undefined : 'auth-password-error'}
              onChange={(event) => form.setField('password', event.target.value)}
              onBlur={() => form.blurField('password')}
            />
            <button
              className={`btn btn-quiet text-button ${styles.passwordToggle}`}
              type="button"
              onClick={() => setShowPassword((current) => !current)}
            >
              {showPassword ? COPY.passwordHide : COPY.passwordShow}
            </button>
            <span className="field-error" id="auth-password-error" role="alert">
              {errorFor('password')}
            </span>
          </div>

          {mode === 'register' && (
            <div className="field">
              <label htmlFor="auth-invite">邀请码</label>
              <input
                id="auth-invite"
                name="inviteCode"
                type="text"
                autoComplete="off"
                value={form.values.inviteCode}
                disabled={form.submitting}
                aria-invalid={errorFor('inviteCode') !== undefined}
                aria-describedby="auth-invite-hint auth-invite-error"
                onChange={(event) => form.setField('inviteCode', event.target.value)}
                onBlur={() => form.blurField('inviteCode')}
              />
              <span className="hint" id="auth-invite-hint">
                {COPY.inviteHint}
              </span>
              <span className="field-error" id="auth-invite-error" role="alert">
                {errorFor('inviteCode')}
              </span>
            </div>
          )}

          <button className="btn btn-primary block" type="submit" disabled={form.submitting}>
            {form.submitting ? pendingLabel : submitLabel}
          </button>

          {/* 提交中的礼貌公告：按钮文字变化对屏幕阅读器不总是即时可闻（页面设计 submitting 行）。 */}
          <p className="form-status" role="status" aria-live="polite">
            {form.submitting ? pendingLabel : ''}
          </p>
        </form>
      </section>

      <p className={styles.switchRow}>
        {mode === 'login' ? (
          <button className="text-button" type="button" onClick={() => setMode('register')}>
            {COPY.toRegister}
          </button>
        ) : (
          <button className="text-button" type="button" onClick={() => setMode('login')}>
            {COPY.toLogin}
          </button>
        )}
      </p>

      {/* 一期不存在自助找回（无邮箱即无自助通道）：如实呈现，不放假的找回入口。 */}
      <p className={styles.note}>{COPY.manualReset}</p>
    </div>
  );
}
