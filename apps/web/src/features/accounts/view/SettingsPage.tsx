/**
 * 模块: features/accounts/view/SettingsPage
 * 职责: 设置页（我的）——账号卡、记录与帮助入口、关于你的数据（含外部模型告知）、
 *       一期边界硬文案、人工重置说明与退出登录（含确认单）
 * 数据来源:
 *   - docs/design/pages/设置页.md: MUST — 全文（布局结构、组件选用、数据与文案、状态覆盖、零 accent）
 *   - docs/design/components.html: MUST — .subpage-head/.tile/.list-row/.btn-secondary/.confirm-sheet
 * 边界:
 *   - 依赖: features/accounts/viewModel/useSettings、shared/ui、react-router
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止弱化一期边界硬文案（AC-10 反向声明逐字呈现：本应用尚未经专业审阅…）
 *   - 禁止放假入口（无「修改密码」「找回密码」按钮——一期改密只能由运营者人工重置）
 *   - 禁止在本页使用 accent（八页里只有设置页零 accent，页面设计 token 使用节）
 */

import { Link } from 'react-router';

import { Icon } from '../../../shared/ui/Icon';
import { AppShell } from '../../../shared/ui/AppShell';
import { ConfirmSheet } from '../../../shared/ui/ConfirmSheet';
import type { AuthPort } from '../application/ports';
import { DATA_FACTS, SETTINGS_COPY, useSettings } from '../viewModel/useSettings';
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
 * 后置: 输出账号卡、记录与帮助入口、数据告知与边界、人工重置说明与退出登录；
 *       登出成功后清会话状态并转登录页
 * 异常: 无（登出异常在确认单内呈现，见 useSettings/useLogout）
 *
 * 展示名从登录/注册响应取得，缓存用于刷新恢复，不构成授权依据。
 * 页面刻意零 accent：工具页不是行动页（页面设计 token 使用节）。
 */
export function SettingsPage({ auth }: SettingsPageProps) {
  const settings = useSettings(auth);
  const { logout } = settings;
  const displayName = settings.accountName ?? SETTINGS_COPY.accountHeadingFallback;

  return (
    <AppShell tab="settings">
      <p className="eyebrow">{SETTINGS_COPY.heading}</p>

      {/* 账号卡：账号名即本页主标题（不再另立一个大标题再重复一次账号名）。 */}
      <section className={styles.account} aria-label="账号">
        <h1 className={styles.accountName}>{displayName}</h1>
        <p className={styles.accountSub}>{SETTINGS_COPY.accountSub}</p>
        {settings.accountName === null && <p className={styles.accountFallback}>{SETTINGS_COPY.accountFallback}</p>}
      </section>

      <section className={styles.links} aria-label={SETTINGS_COPY.linksGroup}>
        <Link className={styles.linkRow} to="/settings/memory">
          <Icon name="person" />
          <span>
            <strong>{SETTINGS_COPY.memoryEntryTitle}</strong>
            <small>{SETTINGS_COPY.memoryEntryBody}</small>
          </span>
          <Icon name="chevron" />
        </Link>
        <Link className={styles.linkRow} to="/guide" state={{ returnTo: '/settings' }}>
          <Icon name="book" />
          <span>
            <strong>{SETTINGS_COPY.guideEntryTitle}</strong>
            <small>{SETTINGS_COPY.guideEntryBody}</small>
          </span>
          <Icon name="chevron" />
        </Link>
      </section>

      <section className={styles.information} aria-labelledby="settings-data">
        <h2 className={styles.groupTitle} id="settings-data">
          {SETTINGS_COPY.dataGroup}
        </h2>
        <dl className={styles.facts}>
          {DATA_FACTS.map((fact) => (
            <div key={fact.title}>
              <dt>{fact.title}</dt>
              <dd>{fact.body}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className={styles.notice} aria-label={SETTINGS_COPY.noticeGroup}>
        <p className={styles.boundary}>{SETTINGS_COPY.boundary}</p>
      </section>

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
