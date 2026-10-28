/**
 * 模块: features/consult/viewModel/useConsultSession
 * 职责: 对话页的会话装配——技能目录、历史水合与失败重试（水合失败不显示空对话）
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 4.4 节（水合流程与失败呈现）
 *   - docs/design/pages/对话页.md: MUST — 状态覆盖表（历史水合 loading/error、401）
 * 边界:
 *   - 依赖: application 用例、domain、viewModel/runStore 与 history
 *   - 被依赖: view 的 ChatPage
 * 禁止行为:
 *   - 禁止把水合失败呈现为空对话（技术设计第 4.4 节）
 *   - 禁止让迟到的水合结果覆盖新会话的状态（会话 id 守卫）
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { ThreadMessageLike } from '@assistant-ui/react';

import { logDiagnostic } from '../../../infrastructure/diagnostics';
import type { ConsultPort } from '../application/ports';
import { ListSkillsUseCase, LoadHistoryUseCase } from '../application/usecases';
import { failureViewFor, type ConsultFailureView } from '../domain/errors';
import { hydrateHistory } from './history';
import { useRunStore } from './runStore';

/** 水合状态：三态显式（骨架屏 / 就绪 / 错误 + 重试）。 */
export type HydrationState =
  | { status: 'loading' }
  | { status: 'ready'; messages: ThreadMessageLike[] }
  | { status: 'error'; failure: ConsultFailureView };

/** 会话装配控制器。 */
export interface ConsultSessionController {
  hydration: HydrationState;
  /** 重新水合（错误态的手动重试、以及订阅不可续传后的自动重读）。 */
  retry(): void;
  /**
   * 第几次水合（从 0 开始）。
   *
   * 页面把它拼进对话工作面的 key：`useLocalRuntime` 一旦建好就不会因为
   * `initialMessages` 变化而重建线程，所以「重新读历史」必须靠重新挂载才真的生效。
   */
  revision: number;
}

/**
 * 装配一条对话的会话级数据。
 *
 * loading 态在渲染期由「已落定的结果是否是本轮任务」派生，而不是在 effect 里先 setState
 * 再发请求：effect 内同步 setState 会多一轮渲染，且把 loading 变成需要维护的第二个状态源。
 *
 * @param sessionId URL 里的对话 id
 * @param consult 咨询端口（组合根注入；测试传替身）
 */
export function useConsultSession(sessionId: string, consult: ConsultPort): ConsultSessionController {
  const [attempt, setAttempt] = useState(0);
  /** 已落定的水合结果 + 它属于哪一轮任务（key 不匹配即视为仍在 loading）。 */
  const [settled, setSettled] = useState<{ key: string; state: HydrationState } | null>(null);
  // 会话身份守卫：切换会话或重新水合后，迟到的响应不得写状态（CORE-03）。
  const generation = useRef(0);
  const taskKey = `${sessionId}#${String(attempt)}`;

  useEffect(() => {
    const current = generation.current + 1;
    generation.current = current;
    useRunStore.getState().reset(sessionId);

    const loadSkills = async (): Promise<void> => {
      try {
        const skills = await new ListSkillsUseCase(consult).execute();
        if (generation.current === current) useRunStore.getState().setSkills(skills);
      } catch (error) {
        // 技能目录取不到不是阻断性失败：选择器只显示「自动」，其余功能照常。
        // 但降级要留痕（不静默吞）。
        logDiagnostic('consult', {
          reason: 'skills-unavailable',
          detail: error instanceof Error ? error.message : String(error),
        });
      }
    };

    const loadHistory = async (): Promise<void> => {
      try {
        const response = await new LoadHistoryUseCase(consult).execute(sessionId);
        if (generation.current !== current) return;
        const hydrated = hydrateHistory(response);
        for (const diagnostic of hydrated.diagnostics) {
          logDiagnostic('history', diagnostic);
        }
        setSettled({ key: taskKey, state: { status: 'ready', messages: hydrated.messages } });
      } catch (error) {
        if (generation.current !== current) return;
        setSettled({ key: taskKey, state: { status: 'error', failure: failureViewFor(error) } });
      }
    };

    void loadSkills();
    void loadHistory();
  }, [sessionId, consult, taskKey]);

  const hydration: HydrationState = settled !== null && settled.key === taskKey ? settled.state : { status: 'loading' };

  const retry = useCallback(() => {
    setAttempt((value) => value + 1);
  }, []);

  return { hydration, retry, revision: attempt };
}
