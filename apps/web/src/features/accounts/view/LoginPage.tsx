/**
 * 模块: features/accounts/view/LoginPage
 * 职责: 登录与注册页——品牌区、模式切换、表单区（账号名/密码/邀请码）、用途与重置告知
 * 数据来源:
 *   - docs/design/pages/登录与注册.md: MUST — 全文（布局结构、组件选用、数据与文案、状态覆盖、动效意图）
 *   - docs/design/components.html: MUST — .panel/.field/.field-error/.form-status 的类名与结构
 * 边界:
 *   - 依赖: features/accounts/viewModel/useLogin（视图流程控制）、shared/ui
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止在本层调用 SDK 或任何 HTTP（端口由 app 装配注入）
 *   - 禁止渲染邮箱字段或找回密码入口（AC-16 的界面侧：一期无邮箱）
 *   - 禁止在提交失败时清空输入（状态保留由 viewModel 保证，View 不得另行重置）
 *   - 禁止把模式切换、密码可见性与文案再写回本层（归 useLogin）
 */

import { BrandMark } from '../../../shared/ui/BrandMark';
import { DeviceFrame } from '../../../shared/ui/DeviceFrame';
import { ErrorCard } from '../../../shared/ui/StatePrimitives';
import type { AuthPort } from '../application/ports';
import type { AuthFieldName } from '../domain/formValidation';
import { LOGIN_COPY, useLogin } from '../viewModel/useLogin';
import styles from './loginPage.module.css';

/** 登录页 props：认证端口经 props 注入（组合根在 app 层）。 */
export interface LoginPageProps {
  /** 认证端口（可能是 SDK 实现或测试替身）。 */
  auth: AuthPort;
  /** 初始模式；默认登录（页面设计：登录页是每个使用者的第一屏）。 */
  initialMode?: 'login' | 'register';
}

/**
 * 渲染登录/注册页。
 *
 * 前置: 认证端口已装配（SDK init 由 app 层负责）
 * 后置: 输出 DeviceFrame 包裹的登录/注册页；提交成功后写入会话 store 并转首页，
 *       失败时保留输入并呈现错误
 * 异常: 无（端口异常已由 viewModel 转成服务端错误态）
 */
export function LoginPage({ auth, initialMode = 'login' }: LoginPageProps) {
  const login = useLogin(auth, initialMode);
  const form = login.form;
  const isRegister = login.mode === 'register';

  /** 字段错误只在已触碰时呈现（untouched 态无红色，craft form-validation）。 */
  const errorFor = (field: AuthFieldName): string | undefined =>
    form.touched.has(field) ? form.errors[field] : undefined;

  return (
    <DeviceFrame>
      <div className={`phone-shell ${styles.shell}`}>
        <header className={styles.brand}>
          <span className={styles.brandMark}>
            <BrandMark size="1.15em" />
          </span>
          <div className={styles.brandText}>
            <h1 className={styles.title}>{LOGIN_COPY.title}</h1>
            <p className={styles.tagline}>{LOGIN_COPY.tagline}</p>
          </div>
        </header>
        <p className={styles.intro}>{LOGIN_COPY.intro}</p>

        <section className={`panel ${styles.panel}`} aria-label={isRegister ? '注册账号' : '登录'}>
          {/* 模式切换：标题行右侧一条显式互切按钮，当前态由标题文字承担，
              避免在面板内再出现与主按钮同名的按钮（可访问名不重复）。 */}
          <div className={styles.panelHead}>
            <h2 className={styles.formTitle}>
              {isRegister ? LOGIN_COPY.formTitleRegister : LOGIN_COPY.formTitleLogin}
            </h2>
            <button className={styles.switchLink} type="button" onClick={login.toggleMode}>
              {isRegister ? LOGIN_COPY.toLogin : LOGIN_COPY.toRegister}
            </button>
          </div>

          {/* server-error 与限流共用这一个横幅位置（页面设计状态覆盖表两行同形态）。 */}
          {form.serverError !== null && (
            <ErrorCard
              variant="form"
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
                autoComplete={login.autocompleteFor('account')}
                value={form.values.account}
                disabled={form.submitting}
                aria-invalid={errorFor('account') !== undefined}
                aria-describedby={errorFor('account') === undefined ? 'auth-account-hint' : 'auth-account-error'}
                onChange={(event) => form.setField('account', event.target.value)}
                onBlur={() => form.blurField('account')}
              />
              <span className="hint" id="auth-account-hint">
                {LOGIN_COPY.accountHint}
              </span>
              <span className="field-error" id="auth-account-error" role="alert">
                {errorFor('account')}
              </span>
            </div>

            <div className={`field ${styles.passwordField}`}>
              <label htmlFor="auth-password">密码</label>
              <input
                id="auth-password"
                name="password"
                type={login.showPassword ? 'text' : 'password'}
                autoComplete={login.autocompleteFor('password')}
                value={form.values.password}
                disabled={form.submitting}
                aria-invalid={errorFor('password') !== undefined}
                aria-describedby={errorFor('password') === undefined ? undefined : 'auth-password-error'}
                onChange={(event) => form.setField('password', event.target.value)}
                onBlur={() => form.blurField('password')}
              />
              <button
                className={`text-button ${styles.passwordToggle}`}
                type="button"
                onClick={login.togglePasswordVisibility}
              >
                {login.showPassword ? LOGIN_COPY.passwordHide : LOGIN_COPY.passwordShow}
              </button>
              <span className="field-error" id="auth-password-error" role="alert">
                {errorFor('password')}
              </span>
            </div>

            {isRegister && (
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
                  {LOGIN_COPY.inviteHint}
                </span>
                <span className="field-error" id="auth-invite-error" role="alert">
                  {errorFor('inviteCode')}
                </span>
              </div>
            )}

            <button className="btn btn-primary block" type="submit" disabled={form.submitting}>
              {form.submitting ? login.pendingLabel : login.submitLabel}
            </button>

            {/* 提交中的礼貌公告：按钮文字变化对屏幕阅读器不总是即时可闻（页面设计 submitting 行）。 */}
            <p className="form-status" role="status" aria-live="polite">
              {form.submitting ? login.pendingLabel : ''}
            </p>
          </form>
        </section>

        <p className={styles.notice}>{LOGIN_COPY.notice}</p>

        <p className={styles.help}>{LOGIN_COPY.resetNote}</p>
      </div>
    </DeviceFrame>
  );
}
