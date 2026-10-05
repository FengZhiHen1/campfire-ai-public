/**
 * 模块: src/app/PlaceholderPage.test
 * 职责: 「没有内容的页面」两个方向的行为守卫——占位页必须说建设中，404 不许说
 * 数据来源:
 *   - src/app/PlaceholderPage.tsx: MUST — 本组件自己的禁止行为（占位必须说明这是什么页、为何还没内容）
 *   - apps/../routes.test.tsx: MUST — 404 方向由路由表用例承担，本文件承担占位方向
 * 边界:
 *   - 依赖: app/PlaceholderPage、app/routes 的 routeElement、react-router 的内存路由
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止在用例里复制路由表的映射逻辑（那会让守卫与被守卫的代码各写一份，改坏产品代码仍全绿）
 *
 * 为什么这个方向**必须单独测**：`APP_ROUTES` 的 9 条路由**全部**有 element 工厂，
 * 所以 `routeElement` 里「省略 element ⇒ 渲染建设中占位」那条分支在走路由表的用例里不可达
 * ——只测 `/nope` 的话，把这条分支一起改坏（例如把 'building' 也换成 'missing'）不会有任何
 * 用例变红（T30 §三-② 的「两个方向都要能红」）。
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, useRoutes } from 'react-router';

import { PlaceholderPage, type PlaceholderPageProps } from './PlaceholderPage';
import { routeElement, type AppRoute } from './routes';

/**
 * 机械守卫：`reason` 必须保持**必填**。
 *
 * 本缺陷的修法依赖「调用方必须说出原因」，一旦有人为了调用方便加回默认值
 * （`reason = 'building'` 或 `'missing'`），两种默认值都会重新引入一类缺陷：
 * 前者让新 404 类页面重现「没有这一页 / 这一页在建设中」并置，后者让新占位页静默
 * 丢掉「本页尚在建设中。」。
 *
 * 判据是双向的：reason 必填时本类型求值为 `true`（下面这行能通过）；
 * 一旦它变成可选，`{} extends Pick<...>` 成立 ⇒ 类型变 `never` ⇒ `tsc --noEmit` 失败。
 * ⇒ 这条守卫**会失败**，不是永远为真的装饰。
 */
type ReasonMustStayRequired = {} extends Pick<PlaceholderPageProps, 'reason'> ? never : true;
const REASON_MUST_STAY_REQUIRED: ReasonMustStayRequired = true;

describe('占位页（本页没有内容的两种原因）', () => {
  it('reason 为 building 时必须说明在建设中，且标题与说明仍在', () => {
    render(<PlaceholderPage title="档案" description="支持对象档案：当前认识、待确认候选与补充。" reason="building" />);

    expect(screen.getByRole('heading', { name: '档案', level: 1 })).toBeDefined();
    expect(screen.getByText('支持对象档案：当前认识、待确认候选与补充。')).toBeDefined();
    // 本方向是「占位必须说明自己为何没内容」那条禁止行为的可执行形态。
    expect(screen.getByText('本页尚在建设中。')).toBeDefined();
  });

  it('reason 为 missing 时不得说明在建设中，且标题与说明仍在', () => {
    render(<PlaceholderPage title="页面不存在" description="这个地址没有对应页面，请从首页重新进入。" reason="missing" />);

    expect(screen.getByRole('heading', { name: '页面不存在', level: 1 })).toBeDefined();
    expect(screen.getByText('这个地址没有对应页面，请从首页重新进入。')).toBeDefined();
    expect(screen.queryByText('本页尚在建设中。')).toBeNull();
  });

  it('reason 保持必填（加回默认值会让 tsc 失败）', () => {
    expect(REASON_MUST_STAY_REQUIRED).toBe(true);
  });

  it('省略 element 的路由经产品自己的 routeElement 渲染，仍必须出现「本页尚在建设中。」', () => {
    // 这条是用例里唯一覆盖 routeElement 占位分支的路径——它走的是产品代码，
    // 不是用例复制的映射逻辑。
    const placeholderRoute: AppRoute = {
      path: '/wip',
      title: '尚未建成的页面',
      description: '这一页建成后会做什么。',
      requiresSession: false,
    };

    function ProbedRoutes() {
      return useRoutes([{ path: placeholderRoute.path, element: routeElement(placeholderRoute) }]);
    }

    render(
      <MemoryRouter initialEntries={['/wip']}>
        <ProbedRoutes />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: '尚未建成的页面', level: 1 })).toBeDefined();
    expect(screen.getByText('本页尚在建设中。')).toBeDefined();
  });

  it('已有 element 的路由经 routeElement 交给页面的元素工厂（占位分支不会被误用）', () => {
    const builtRoute: AppRoute = {
      path: '/built',
      title: '已建成',
      description: '不该被渲染。',
      requiresSession: false,
      element: () => <p>真实页面内容</p>,
    };

    function ProbedRoutes() {
      return useRoutes([{ path: builtRoute.path, element: routeElement(builtRoute) }]);
    }

    render(
      <MemoryRouter initialEntries={['/built']}>
        <ProbedRoutes />
      </MemoryRouter>,
    );

    expect(screen.getByText('真实页面内容')).toBeDefined();
    expect(screen.queryByText('本页尚在建设中。')).toBeNull();
    expect(screen.queryByText('不该被渲染。')).toBeNull();
  });
});
