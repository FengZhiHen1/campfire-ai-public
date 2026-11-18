/**
 * 模块: features/accounts/view/SettingsPage
 * 职责: 设置页（我的）——账号卡、原生感设置入口列表（我提过的事 / 使用说明 / 关于篝火智答）、
 *       人工重置说明与退出登录（含确认单）。数据用途与使用边界已改由「关于篝火智答」次级页承载。
 * 数据来源:
 *   - docs/design/pages/设置页.md: MUST — 布局结构（一级页面：账号、记录与帮助、账号操作）
 *   - docs/design/components.html: MUST — .list-row/.btn-secondary/.confirm-sheet
 * 边界:
 *   - 依赖: features/accounts/viewModel/useSettings、shared/ui、react-router
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止弱化一期边界硬文案（AC-10 反向声明逐字呈现：它现由「关于篝火智答」页承载）
 *   - 禁止放假入口（无「修改密码」「找回密码」按钮——一期改密只能由运营者人工重置）
 *   - 禁止在本页使用 accent（八页里只有设置页零 accent，页面设计 token 使用节）
 */

import { Link } from 'react-router';

import { Icon } from '../../../shared/ui/Icon';
import { AppShell } from '../../../shared/ui/AppShell';
import { ConfirmSheet } from '../../../shared/ui/ConfirmSheet';
import type { AuthPort } from '../application/ports';
import { SETTINGS_COPY, useSettings } from '../viewModel/useSettings';
import styles from './settingsPage.module.css';

/** 设置页 props：认证端口经 props 注入（登出走 accounts 端口）。 */
export interface SettingsPageProps {
  /** 认证端口；未提供时不渲染退出登录（页面在不装配端口的测试里仍可渲染）。 */
  auth: AuthPort;
}

/**
 * 渲染设置页。
 *
 * 前置: auth 已装配
 * 后置: 输出账号卡、设置入口列表、人工重置说明与退出登录；
 *       登出成功后清会话状态并转登录页
 * 异常: 无（登出异常在确认单内呈现，见 useSettings/useLogout）
 *
 * 展示名从登录/注册响应取得，缓存用于刷新恢复，不构成授权依据。
 * 页面刻意零 accent：工具页不是行动页（页面设计 token 使用节）。
 *
 * 结构：数据用途与使用边界不再本页平铺展开，而是像原生设置一样，收进
 * 「关于篝火智答」次级页（/settings/about）——一级页只留可达入口，减少长说明堆叠。
 */
export function SettingsPage({ auth }: SettingsPageProps) {
  const settings = useSettings(auth);
  const { logout } = settings;
  const displayName = settings.accountName ?? SETTINGS_COPY.accountHeadingFallback;

  return (
    <AppShell tab="settings">
      <p className="eyebrow">{SETTINGS_COPY.heading}</p>

      {/* 账号卡：一行主标题 + 一行身份说明，不重复「个人账号」。 */}
      <section className={styles.account} aria-label="账号">
        <h1 className={styles.accountName}>{displayName}</h1>
        <p className={styles.accountSub}>
          {settings.accountName === null ? SETTINGS_COPY.accountFallback : SETTINGS_COPY.accountSub}
        </p>
      </section>

      <nav className={styles.links} aria-label={SETTINGS_COPY.linksGroup}>
        <Link className={styles.linkRow} to="/settings/memory">
          <span className={styles.entryIcon}>
            <Icon name="person" />
          </span>
          <span className={styles.entryText}>
            <strong>{SETTINGS_COPY.memoryEntryTitle}</strong>
            <small>{SETTINGS_COPY.memoryEntryBody}</small>
          </span>
          <span className={styles.entryChevron}>
            <Icon name="chevron" />
          </span>
        </Link>
        <Link className={styles.linkRow} to="/guide" state={{ returnTo: '/settings' }}>
          <span className={styles.entryIcon}>
            <Icon name="book" />
          </span>
          <span className={styles.entryText}>
            <strong>{SETTINGS_COPY.guideEntryTitle}</strong>
            <small>{SETTINGS_COPY.guideEntryBody}</small>
          </span>
          <span className={styles.entryChevron}>
            <Icon name="chevron" />
          </span>
        </Link>
        <Link className={styles.linkRow} to="/settings/about" state={{ returnTo: '/settings' }}>
          <span className={styles.entryIcon}>
            <Icon name="shield" />
          </span>
          <span className={styles.entryText}>
            <strong>{SETTINGS_COPY.aboutEntryTitle}</strong>
            <small>{SETTINGS_COPY.aboutEntryBody}</small>
          </span>
          <span className={styles.entryChevron}>
            <Icon name="chevron" />
          </span>
        </Link>
      </nav>

      <section className={styles.actions} aria-label="账号操作">
        <button className="btn btn-secondary block" type="button" onClick={logout.open}>
          {SETTINGS_COPY.logout}
        </button>
        <p className={styles.resetNote}>{SETTINGS_COPY.resetNote}</p>
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
 * 为什么不用原生 `<dialog>.showModal()`：jsdom 未实现 showModal/close/show，
 * 且 `showModal()` 的 top layer 会把包含块从 .device-screen 换成视口，确认单在宽视口下
 * 甩出手机外壳（global.css 中 .device 的 transform 是承重属性）。
 * 模态语义（遮罩、焦点进入、焦点陷阱、Esc 关闭、背景 inert）由 shared/ui/ConfirmSheet 手工补齐。
 *
 * 前置: 无
 * 后置: 输出 .confirm-sheet 容器与遮罩层；提交中按钮进入 loading；有错误时内联呈现并保留「重试」
 * 异常: 无
 */
function LogoutConfirmSheet({ submitting, error, onCancel, onConfirm }: LogoutConfirmSheetProps) {
  return (
    <ConfirmSheet labelledBy="logout-sheet-title" onDismiss={onCancel}>
      <h2 id="logout-sheet-title">{SETTINGS_COPY.sheetTitle}</h2>
      <p>{SETTINGS_COPY.sheetBody}</p>
      {error !== null && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <div className="button-row">
        <button className="btn btn-quiet" type="button" onClick={onCancel} disabled={submitting}>
          {SETTINGS_COPY.sheetCancel}
        </button>
        <button className="btn btn-secondary" type="button" onClick={onConfirm} disabled={submitting}>
          {submitting ? SETTINGS_COPY.logoutPending : error === null ? SETTINGS_COPY.sheetConfirm : '重试'}
        </button>
      </div>
    </ConfirmSheet>
  );
}
