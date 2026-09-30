/**
 * 模块: app/routes
 * 职责: 路由表的单一事实源——路径、标题、占位说明与守卫需求都在这张表里
 * 数据来源:
 *   - docs/项目结构设计.md: MUST — 第 9 节（路由与技能选择：对话 id 在 URL 中）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 端点路径形状
 *   - docs/design/pages/: SHOULD — 路由名与页面设计文档一一对应
 * 边界:
 *   - 依赖: app/PlaceholderPage、app/RequireSession、react-router 的 RouteObject 类型
 *   - 被依赖: app/App
 * 禁止行为:
 *   - 禁止在表里写组件实现（表只描述路由，页面实现归 features/<f>/view）
 *   - 禁止为未开工特性发明路由（路径以任务包裁决的清单为准）
 */

import type { RouteObject } from 'react-router';

import { LoginPage } from './LoginPage';
import { PlaceholderPage } from './PlaceholderPage';
import { RequireSession } from './RequireSession';

/** 一条前端路由的描述；守卫需求是数据而不是散落在 JSX 里的条件。 */
export interface AppRoute {
  /** 路由路径（React Router 语法）。 */
  path: string;
  /** 页面标题（中文）。 */
  title: string;
  /** 一行说明（中文）：本页建成后做什么。 */
  description: string;
  /** 是否要求已登录会话（体验层守卫，不构成权限证明）。 */
  requiresSession: boolean;
}

/**
 * 一期路由清单。
 *
 * 路径对齐后端契约：咨询面端点是 /consult/*，案例库浏览页 deep-link 落 /cases?item=，
 * 记忆面承载页面是设置页下的次级页（记忆面契约第 1 节）。
 * 未登录时全部业务路由经 RequireSession 转 /login；/login 自身不设守卫（否则会自转死循环）。
 */
export const APP_ROUTES: readonly AppRoute[] = [
  { path: '/', title: '篝火智答', description: '首页：应急入口与日常咨询的起点。', requiresSession: true },
  { path: '/consult', title: '咨询记录', description: '历史会话列表，回看过去的咨询。', requiresSession: true },
  {
    path: '/consult/sessions/:sessionId',
    title: '对话',
    description: '日常咨询主界面：消息流、依据区与提问卡。',
    requiresSession: true,
  },
  {
    path: '/consult/emergency',
    title: '应急现场采集',
    description: '八项现场情况采集，提交后直接进入对话。',
    requiresSession: true,
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
  { path: '/settings', title: '我的', description: '设置：账号、关于你的数据与使用说明入口。', requiresSession: true },
  {
    path: '/settings/memory',
    title: '记忆',
    description: '查看、纠正与删除属于本账号的记忆时间线。',
    requiresSession: true,
  },
  { path: '/guide', title: '使用说明', description: '产品怎么用、能做什么与不能做什么。', requiresSession: true },
];

/**
 * 生成 React Router 的路由对象数组。
 *
 * 前置: APP_ROUTES 非空（静态配置保证）
 * 后置: 返回覆盖 /login、APP_ROUTES 全部路径与通配路径的路由数组；
 *       requiresSession 为真的项包在 RequireSession 下，未匹配路径渲染「页面不存在」占位
 * 异常: 无
 */
export function buildRouteObjects(): RouteObject[] {
  const businessRoutes: RouteObject[] = APP_ROUTES.map((route) => ({
    path: route.path,
    element: (
      <RequireSession enabled={route.requiresSession}>
        <PlaceholderPage title={route.title} description={route.description} />
      </RequireSession>
    ),
  }));

  return [
    { path: '/login', element: <LoginPage /> },
    ...businessRoutes,
    {
      path: '*',
      element: <PlaceholderPage title="页面不存在" description="这个地址没有对应页面，请从首页重新进入。" />,
    },
  ];
}
