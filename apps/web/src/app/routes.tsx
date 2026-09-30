/**
 * 模块: app/routes
 * 职责: 路由表的单一事实源——路径、标题、页面元素与守卫需求都在这张表里
 * 数据来源:
 *   - docs/项目结构设计.md: MUST — 第 9 节（路由与技能选择：对话 id 在 URL 中）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 端点路径形状
 *   - docs/design/pages/: MUST — 路由名与页面设计文档一一对应（十个路径）
 * 边界:
 *   - 依赖: app/PlaceholderPage、app/pages/*、features/accounts/view/*、app/RequireSession
 *   - 被依赖: app/App
 * 禁止行为:
 *   - 禁止为未开工特性发明路由（路径以任务包裁决的清单为准）
 *   - 禁止把已建成页面的实现写进本文件（页面归 app/pages 与 features/<f>/view）
 */

import type { ReactElement } from 'react';
import type { RouteObject } from 'react-router';

import { GuidePage } from './pages/GuidePage';
import { HomePage } from './pages/HomePage';
import { PlaceholderPage } from './PlaceholderPage';
import { RequireSession } from './RequireSession';
import { LoginPage } from '../features/accounts/view/LoginPage';
import { SettingsPage } from '../features/accounts/view/SettingsPage';
import { useSessionStore } from '../features/accounts/viewModel/sessionStore';
import { ChatPage } from '../features/consult/view/ChatPage';
import { ConsultListPage } from '../features/consult/view/ConsultListPage';
import { EmergencyFormPage } from '../features/consult/view/EmergencyFormPage';
import { supertokensAuthPort } from '../infrastructure/auth/authPort';
import { createConsultApi } from '../infrastructure/consult/consultPort';

/**
 * 咨询面端口（组合根）。
 *
 * 为什么在这里建实例而不是 App：路由表已经是各页面的装配点（登录页与设置页同样在表里
 * 收端口）。401 的接线必须在这里给：JSON 请求的 401 由 infrastructure/http/client 的
 * 全局处置回调负责（App 装配），而 SSE 请求不经过它，所以咨询端口自带一个回调，
 * 两者最终落到同一个动作（清本地状态 → 守卫把使用者送到登录页）。
 */
const consultPort = createConsultApi({
  onUnauthorized: () => {
    useSessionStore.getState().markAnonymous();
  },
});

/** 一条前端路由的描述；守卫需求是数据而不是散落在 JSX 里的条件。 */
export interface AppRoute {
  /** 路由路径（React Router 语法）。 */
  path: string;
  /** 页面标题（中文）。 */
  title: string;
  /** 一行说明（中文）：本页建成后做什么；仅在页面未建成时作为占位文案呈现。 */
  description: string;
  /** 是否要求已登录会话（体验层守卫，不构成权限证明）。 */
  requiresSession: boolean;
  /**
   * 已建成页面的元素工厂；省略表示该页仍是占位（PlaceholderPage）。
   *
   * 为什么是工厂而不是元素：元素在模块加载时就构造，而页面需要从 app 层拿到端口装配；
   * 工厂把装配推迟到路由真正渲染时，也让「是否已是真页面」在表里一眼可辨。
   */
  element?: () => ReactElement;
}

/**
 * 一期路由清单。
 *
 * 路径对齐后端契约：咨询面端点是 /consult/*，案例库浏览页 deep-link 落 /cases?item=，
 * 记忆面承载页面是设置页下的次级页（记忆面契约第 1 节）。
 * 未登录时全部业务路由经 RequireSession 转 /login；/login 自身不设守卫（否则会自转死循环）。
 */
export const APP_ROUTES: readonly AppRoute[] = [
  {
    path: '/',
    title: '篝火智答',
    description: '首页：应急入口与日常咨询的起点。',
    requiresSession: true,
    element: () => <HomePage />,
  },
  {
    path: '/consult',
    title: '咨询记录',
    description: '历史会话列表，回看过去的咨询。',
    requiresSession: true,
    element: () => <ConsultListPage consult={consultPort} />,
  },
  {
    path: '/consult/sessions/:sessionId',
    title: '对话',
    description: '日常咨询主界面：消息流、依据区与提问卡。',
    requiresSession: true,
    element: () => <ChatPage consult={consultPort} />,
  },
  {
    path: '/consult/emergency',
    title: '应急现场采集',
    description: '八项现场情况采集，提交后直接进入对话。',
    requiresSession: true,
    element: () => <EmergencyFormPage consult={consultPort} />,
  },
  {
    path: '/profile',
    title: '档案',
    description: '支持对象档案：当前认识、待确认候选与补充。',
    requiresSession: true,
  },
  {
    path: '/cases',
    title: '案例库',
    description: '公开案例浏览与检索，支持从引用跳转定位。',
    requiresSession: true,
  },
  {
    path: '/settings',
    title: '我的',
    description: '设置：账号、关于你的数据与使用说明入口。',
    requiresSession: true,
    element: () => <SettingsPage auth={supertokensAuthPort} />,
  },
  {
    path: '/settings/memory',
    title: '记忆',
    description: '查看、纠正与删除属于本账号的记忆时间线。',
    requiresSession: true,
  },
  {
    path: '/guide',
    title: '使用说明',
    description: '产品怎么用、能做什么与不能做什么。',
    requiresSession: true,
    element: () => <GuidePage />,
  },
];

/**
 * 生成 React Router 的路由对象数组。
 *
 * 前置: APP_ROUTES 非空（静态配置保证）
 * 后置: 返回覆盖 /login、APP_ROUTES 全部路径与通配路径的路由数组；
 *       requiresSession 为真的项包在 RequireSession 下；未建成页面渲染占位，
 *       未匹配路径渲染「页面不存在」占位
 * 异常: 无
 */
export function buildRouteObjects(): RouteObject[] {
  const businessRoutes: RouteObject[] = APP_ROUTES.map((route) => ({
    path: route.path,
    element: (
      <RequireSession enabled={route.requiresSession}>
        {route.element === undefined ? (
          <PlaceholderPage title={route.title} description={route.description} />
        ) : (
          route.element()
        )}
      </RequireSession>
    ),
  }));

  return [
    // /login 不受守卫保护：登录页是未登录可达的唯一业务页面，守卫它会自转死循环。
    { path: '/login', element: <LoginPage auth={supertokensAuthPort} /> },
    ...businessRoutes,
    {
      path: '*',
      element: <PlaceholderPage title="页面不存在" description="这个地址没有对应页面，请从首页重新进入。" />,
    },
  ];
}
