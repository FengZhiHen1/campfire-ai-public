/**
 * 模块: features/accounts/view/SettingsPage
 * 职责: 设置页（我的）——账号卡、关于你的数据（含记忆页入口）、一期边界硬文案与退出登录
 * 数据来源:
 *   - docs/design/pages/设置页.md: MUST — 全文（布局结构、组件选用、数据与文案、状态覆盖、动效意图）
 *   - docs/design/components.html: MUST — .page-head/.tile/.list-row/.btn-secondary/.confirm-sheet
 * 边界:
 *   - 依赖: features/accounts/viewModel（sessionStore、useLogout）、shared/ui、react-router
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止弱化一期边界硬文案（AC-10 反向声明逐字呈现：本应用尚未经专业审阅…）
 *   - 禁止放假入口（无「修改密码」「找回密码」按钮——一期改密只能由运营者人工重置）
 *   - 禁止在本页使用 accent（八页里只有设置页零 accent，页面设计 token 使用节）
 */

import { Link, useNavigate } from 'react-router';

import { Icon } from '../../../shared/ui/Icon';
import { AppShell } from '../../../shared/ui/AppShell';
import { ConfirmSheet } from '../../../shared/ui/ConfirmSheet';
import { useSessionStore } from '../viewModel/sessionStore';
import { useLogout } from '../viewModel/useLogout';
import type { AuthPort } from '../application/ports';
import styles from './settingsPage.module.css';

/** 设置页 props：认证端口经 props 注入（登出走 accounts 端口）。 */
export interface SettingsPageProps {
  /** 认证端口；未提供时不渲染退出登录（页面在不装配端口的测试里仍可渲染）。 */
  auth: AuthPort;
}

/** 页面文案（页面设计「布局结构」与「数据与文案」节的成稿，逐字呈现）。 */
const COPY = {
  heading: '我的',
  accountSub: '个人账号 · 邀请码注册',
  accountFallback: '当前登录会话',
  dataGroup: '关于你的数据',
  usageTitle: '咨询记录怎么用',
  usageBody: '本次输入的内容用于生成回答，并按你的确认累积到档案与记忆',
  visibilityTitle: '谁可见',
  visibilityBody: '只有你的账号可以看到；登录才能使用全部功能',
  modelTitle: '会送去外部模型吗',
  modelBody: '咨询内容会发送给模型服务处理后返回',
  memoryEntryTitle: '我提过的事',
  memoryEntryBody: '看看系统记住了什么，可以纠正或删除',
  noticeGroup: '使用须知',
  // 一期边界硬文案：AC-10 反向声明，逐字呈现，不得弱化（页面设计设置页第 4 条）。
  // 设计原文的引号在句末句号之前闭合，硬文案本身不含句号（照抄成「…急救电话。」会多一个字符）。
  boundary: '本应用尚未经专业审阅，不能替代专业服务；遇到紧急医疗情况请直接就医或拨打急救电话',
  resetNote: '忘记密码？请联系运营者人工重置',
  logout: '退出登录',
  logoutPending: '正在退出…',
  sheetTitle: '退出登录？',
  sheetBody: '退出后需要重新登录',
  sheetCancel: '取消',
  sheetConfirm: '退出',
} as const;

/**
 * 渲染设置页。
 *
 * 前置: auth 已装配
 * 后置: 输出账号卡、两张说明卡与操作区；登出成功后清会话状态并转登录页
 * 异常: 无（登出异常在确认单内呈现，见 useLogout）
 *
 * 展示名从登录/注册响应取得，缓存用于刷新恢复，不构成授权依据。
 */
export function SettingsPage({ auth }: SettingsPageProps) {
  const navigate = useNavigate();
  const account = useSessionStore((state) => state.account);
  const markAnonymous = useSessionStore((state) => state.markAnonymous);

  const logout = useLogout(auth, () => {
    // 登出成功后清本地状态并回登录页（认证与账号第 6 节，与 401 同路）。
    markAnonymous();
    void navigate('/login', { replace: true });
  });

  return (
    <AppShell tab="settings">

      <header className="page-head"><div><h1 className={styles.heading}>{COPY.heading}</h1><p className="hint">账号、记录，以及你需要了解的事。</p></div></header>
      <section className={styles.account} aria-labelledby="settings-account">
        <h2 className={styles.accountName} id="settings-account">{account?.accountName ?? '个人账号'}</h2>
        <p className={styles.accountSub}>{COPY.accountSub}</p>
        {(account === null || account.accountName === null) && <p className="meta">{COPY.accountFallback}</p>}
      </section>
      <section className={styles.links} aria-label="记录与帮助">
        <Link className={styles.linkRow} to="/settings/memory">
          <Icon name="person" /><span><strong>{COPY.memoryEntryTitle}</strong><small>{COPY.memoryEntryBody}</small></span><Icon name="chevron" />
        </Link>
        <Link className={styles.linkRow} to="/guide" state={{ returnTo: '/settings' }}>
          <Icon name="book" /><span><strong>使用说明</strong><small>咨询、档案与记忆怎么用</small></span><Icon name="chevron" />
        </Link>
      </section>
      <section className={styles.information} aria-labelledby="settings-data">
        <h2 className={styles.groupTitle} id="settings-data"><Icon name="shield" />{COPY.dataGroup}</h2>
        <dl className={styles.facts}>
          <div><dt>{COPY.usageTitle}</dt><dd>{COPY.usageBody}</dd></div>
          <div><dt>{COPY.visibilityTitle}</dt><dd>{COPY.visibilityBody}</dd></div>
          <div><dt>{COPY.modelTitle}</dt><dd>{COPY.modelBody}</dd></div>
        </dl>
      </section>
      <section className={styles.notice} aria-labelledby="settings-notice">
        <h2 className={styles.groupTitle} id="settings-notice">{COPY.noticeGroup}</h2>
        <p className={styles.boundary}>{COPY.boundary}</p>
      </section>
      <section className={styles.actions} aria-label="账号操作">
        <button className="btn btn-secondary block" type="button" onClick={logout.open}>{COPY.logout}</button>
        <p className={styles.resetNote}>{COPY.resetNote}</p>
      </section>
      {logout.confirming && (
        <LogoutConfirmSheet
          submitting={logout.submitting}
          error={logout.error}
          onCancel={logout.close}
          onConfirm={() => {
            void logout.confirm();
          }}
        />
      )}
    </AppShell>
  );
}

/** 登出确认单 props。 */
interface LogoutConfirmSheetProps {
  submitting: boolean;
  error: string | null;
  onCancel(): void;
  onConfirm(): void;
}

/**
 * 渲染登出确认单（契约组件 .confirm-sheet）。
 *
 * 为什么不用原生 `<dialog>.showModal()`：jsdom 未实现 showModal/close/show
 * （三者全为 undefined），而前端测试环境是 jsdom；且 `showModal()` 的 top layer
 * 会把包含块从 .device-screen 换成视口，确认单在宽视口下变成 `--phone-shell-max`
 * 宽（实测 left 445 → 400、width 390 → 480）而甩出手机外壳——那条 transform 是
 * global.css 的承重属性，其注释明文点名它存在的目的之一就是让 .confirm-sheet 收进外壳。
 * 模态语义（遮罩、焦点进入、焦点陷阱、Esc 关闭、背景 inert）因此由
 * shared/ui/ConfirmSheet 手工补齐，并如实声称 `aria-modal="true"`。
 * 已知残余（比原生模态少一项）：层级由 z-index 而非 top layer 保证。
 *
 * 前置: 无
 * 后置: 输出 .confirm-sheet 容器与遮罩层；提交中按钮进入 loading；有错误时内联呈现并保留「重试」
 * 异常: 无
 */
function LogoutConfirmSheet({ submitting, error, onCancel, onConfirm }: LogoutConfirmSheetProps) {
  return (
    <ConfirmSheet labelledBy="logout-sheet-title" onDismiss={onCancel}>
      <h2 id="logout-sheet-title">{COPY.sheetTitle}</h2>
      <p>{COPY.sheetBody}</p>
      {error !== null && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <div className="button-row">
        <button className="btn btn-quiet" type="button" onClick={onCancel} disabled={submitting}>
          {COPY.sheetCancel}
        </button>
        <button className="btn btn-secondary" type="button" onClick={onConfirm} disabled={submitting}>
          {submitting ? COPY.logoutPending : error === null ? COPY.sheetConfirm : '重试'}
        </button>
      </div>
    </ConfirmSheet>
  );
}
