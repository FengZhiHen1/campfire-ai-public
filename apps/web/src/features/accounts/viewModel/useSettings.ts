/**
 * 模块: features/accounts/viewModel/useSettings
 * 职责: 设置页（我的）的视图流程控制——账号展示、登出编排与页面成稿文案
 * 数据来源:
 *   - docs/design/pages/设置页.md: MUST — 全文（布局结构、数据与文案、状态覆盖表、零 accent）
 *   - docs/技术设计/technical-details/认证与账号.md: MUST — 第 6 节（登出后清状态回登录页）
 * 边界:
 *   - 依赖: features/accounts/viewModel（sessionStore、useLogout）、application/ports
 *   - 被依赖: features/accounts/view 的设置页
 * 禁止行为:
 *   - 禁止在本层渲染任何东西（本 hook 只出状态、回调和文案）
 *   - 禁止弱化一期边界硬文案（AC-10 反向声明逐字呈现）
 *   - 禁止把登出失败当成已登出（成功与否由 useLogout 如实回报）
 */

import { useNavigate } from 'react-router';

import type { AuthPort } from '../application/ports';
import { useSessionStore } from './sessionStore';
import { useLogout, type LogoutController } from './useLogout';

/** 设置页的成稿文案（页面设计「数据与文案」节，逐字呈现）。 */
export const SETTINGS_COPY = {
  heading: '我的',
  accountHeadingFallback: '个人账号',
  accountSub: '个人账号 · 邀请码注册',
  accountFallback: '当前登录会话',
  linksGroup: '记录与帮助',
  memoryEntryTitle: '我提过的事',
  memoryEntryBody: '看看系统记住了什么，可以纠正或删除',
  guideEntryTitle: '使用说明',
  guideEntryBody: '咨询、档案与记忆怎么用',
  dataGroup: '关于你的数据',
  usageTitle: '咨询记录怎么用',
  usageBody: '本次输入的内容用于生成回答，并按你的确认累积到档案与记忆',
  visibilityTitle: '谁可见',
  visibilityBody: '只有你的账号可以看到；登录才能使用全部功能',
  modelTitle: '会送去外部模型吗',
  modelBody: '咨询内容会发送给模型服务处理后返回',
  noticeGroup: '使用须知',
  // 一期边界硬文案：AC-10 反向声明，逐字呈现，不得弱化。原文引号在句末句号前闭合，故本条不含句号。
  boundary: '本应用尚未经专业审阅，不能替代专业服务；遇到紧急医疗情况请直接就医或拨打急救电话',
  resetNote: '忘记密码？请联系运营者人工重置',
  logout: '退出登录',
  logoutPending: '正在退出…',
  sheetTitle: '退出登录？',
  sheetBody: '退出后需要重新登录',
  sheetCancel: '取消',
  sheetConfirm: '退出',
} as const;

/** 「关于你的数据」三项告知（顺序即呈现顺序）。 */
export const DATA_FACTS = [
  { title: SETTINGS_COPY.usageTitle, body: SETTINGS_COPY.usageBody },
  { title: SETTINGS_COPY.visibilityTitle, body: SETTINGS_COPY.visibilityBody },
  { title: SETTINGS_COPY.modelTitle, body: SETTINGS_COPY.modelBody },
] as const;

/** useSettings 的返回形状（View 只依赖这些）。 */
export interface SettingsController {
  /** 账号展示名；null 表示本地会话有、但没拿到展示名（冷启动）。 */
  accountName: string | null;
  /** 登出控制器（确认单开关、提交中、错误与重试）。 */
  logout: LogoutController;
}

/**
 * 设置页视图流程控制器。
 *
 * @param auth 认证端口（组合根注入；登出走 accounts 端口）。
 *
 * 把登出编排（确认单 → 提交 → 成功清会话回登录页 / 失败保留上下文）从 View 收拢到此处：
 * View 只负责按状态渲染，不再自己拼事务顺序。清本地状态与跳转由本 hook 在成功回调里做，
 * 与「401 同路、回登录页」保持同一语义。
 */
export function useSettings(auth: AuthPort): SettingsController {
  const navigate = useNavigate();
  const account = useSessionStore((state) => state.account);
  const markAnonymous = useSessionStore((state) => state.markAnonymous);

  const logout = useLogout(auth, () => {
    // 登出成功后清本地状态并回登录页（认证与账号第 6 节，与 401 同路）。
    markAnonymous();
    void navigate('/login', { replace: true });
  });

  return { accountName: account?.accountName ?? null, logout };
}
