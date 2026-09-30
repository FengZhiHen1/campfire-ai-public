/**
 * 模块: features/accounts/viewModel/sessionStore
 * 职责: 会话存在性的跨页面状态（Zustand），供路由守卫与顶栏消费
 * 数据来源:
 *   - docs/项目结构设计.md: MUST — 第 9 节（状态归属三分：跨介质 UI 状态归 viewModel）
 * 边界:
 *   - 依赖: features/accounts/domain、application
 *   - 被依赖: app 的路由守卫与装配
 * 禁止行为:
 *   - 禁止在 store 里存凭据（凭据在 httpOnly cookie，前端不可读）
 *   - 禁止把 store 当成权限判定（守卫只负责体验）
 */

import { create } from 'zustand';

import type { SessionSnapshot } from '../domain/session';
import { unknownSession } from '../domain/session';
import { ResolveSessionUseCase } from '../application/usecases';
import type { SessionPort } from '../application/ports';

/** 会话 store 的状态与方法。 */
export interface SessionStoreState {
  session: SessionSnapshot;
  /** 用给定端口重新查证会话；查证失败保持 unknown（不得降级为匿名）。 */
  refresh(session: SessionPort): Promise<void>;
  /** 标记为已确认未登录（401 处置路径使用，不经过 SDK 查证）。 */
  markAnonymous(): void;
}

/**
 * 为什么状态初始为 unknown 而不是 anonymous：应用冷启动时尚未查证，直接判匿名会把
 * 已登录用户在刷新页面时弹到登录页（一次误判换取一次闪烁），而判已登录会让守卫失效。
 * unknown 是一个必须被下游显式处理的第三态。
 */
export const useSessionStore = create<SessionStoreState>((set) => ({
  session: unknownSession(),
  async refresh(session: SessionPort) {
    const snapshot = await new ResolveSessionUseCase(session).execute();
    set({ session: snapshot });
  },
  markAnonymous() {
    set({ session: { status: 'anonymous' } });
  },
}));
