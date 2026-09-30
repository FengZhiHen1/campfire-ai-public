/**
 * 模块: features/consult/test/fixtures
 * 职责: 咨询面事件与载荷的测试夹具——按线格式类型同源构造，禁止手写第二份形状
 * 数据来源:
 *   - shared/types/sse: MUST — RunEvent 联合（夹具必须过同一类型）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 4.2 节事件载荷
 * 边界:
 *   - 依赖: shared/types/{sse,consult}
 *   - 被依赖: features/consult 的测试
 * 禁止行为:
 *   - 禁止在夹具里发明契约未定义的字段
 *   - 禁止让夹具绕过类型检查（不用 any 断言；字段缺失必须由类型报错暴露）
 */

import type { HydratedMessage, ListMessagesResponse, SessionSummary } from '../../../shared/types/consult';
import type {
  ActionCardEvent,
  ActionCardSection,
  CitationRecord,
  QuestionEvent,
  QuestionItem,
  RunEvent,
  RunFailedEvent,
  RunFinishedEvent,
  RunStartedEvent,
  TextDeltaEvent,
} from '../../../shared/types/sse';

/** 运行开始。 */
export function runStarted(activatedSkills: readonly string[] = [], runId = 'run-1'): RunStartedEvent {
  return {
    type: 'run_started',
    run_id: runId,
    session_id: 's1',
    surface: 'consult',
    model: 'deepseek-v4.1-flash',
    activated_skills: [...activatedSkills],
    injection_sources: [],
    appended_messages: 1,
  };
}

/** 文本增量。 */
export function textDelta(delta: string): TextDeltaEvent {
  return { type: 'text_delta', delta };
}

/** 正常结束。 */
export function runFinished(): RunFinishedEvent {
  return {
    type: 'run_finished',
    reason: 'completed',
    citations: [],
    usage: { requests: 1, input_tokens: 1, output_tokens: 1, total_tokens: 2 },
    elapsed_seconds: 1,
    compactions: [],
  };
}

/** 异常结束。 */
export function runFailed(code: RunFailedEvent['code'] = 'internal'): RunFailedEvent {
  return {
    type: 'run_failed',
    code,
    detail: '测试夹具',
    citations: [],
    usage: { requests: 1, input_tokens: 1, output_tokens: 1, total_tokens: 2 },
    elapsed_seconds: 1,
    model_reason: null,
    compactions: [],
  };
}

/** 一组结构化提问。 */
export function questionEvent(items: readonly QuestionItem[], batchId = 'b1'): QuestionEvent {
  return { type: 'question', batch_id: batchId, items: [...items] };
}

/** 两道题的常见批次（一题可跳过，一题不可）。 */
export const QUESTION_ITEMS: readonly QuestionItem[] = [
  {
    id: 'q1',
    prompt: '现在还能用口语沟通吗？',
    options: [{ label: '可以' }, { label: '不能', description: '包括只能用手势' }],
    allow_skip: true,
  },
  { id: 'q2', prompt: '有没有可能正在疼痛？', options: [{ label: '是' }, { label: '不确定' }], allow_skip: false },
];

/** 行动卡的一个分节。 */
function section(key: string, heading: string, lines: readonly string[]): ActionCardSection {
  return { key, heading, lines: [...lines] };
}

/** 合规的七节行动卡（顺序即契约的规范顺序）。 */
export function actionCardEvent(overrides: Partial<ActionCardEvent> = {}): ActionCardEvent {
  return {
    type: 'action_card',
    card_id: 'card-1',
    title: '现场行动卡',
    sections: [
      section('status', '当前状态', ['与平时相比：明显变化']),
      section('communicate', '立即怎么沟通', ['一次只问一个问题']),
      section('do_now', '立即做', ['换到安静的地方']),
      section('avoid', '不要做', ['不要突然触碰']),
      section('medical_checks', '需要的医疗检查', ['确认是否存在疼痛']),
      section('safety', '安全措施', ['减少人员围观']),
      section('when_to_escalate', '何时升级', ['出现紧急医疗情况请就医']),
    ],
    states: [
      { key: 'medical_risk', value: 'uncertain' },
      { key: 'deviation', value: 'marked' },
      { key: 'communication', value: 'reduced' },
      { key: 'sensory_load', value: 'unknown' },
    ],
    annotations: [
      // 摊平序号：1=status[0] 2=communicate[0] 3=do_now[0] … 6=safety[0] 7=when_to_escalate[0]。
      { target: '3', kind: 'family_report:likely' },
      { target: '6', kind: 'ai_inference:possible' },
    ],
    ...overrides,
  };
}

/** 一条引用记录（线格式 CitationRecord）。 */
export function citation(citationId = 'c1', reference = '沟通方式记录（虚构样例）'): CitationRecord {
  return {
    citation_id: citationId,
    run_id: 'run-1',
    source: '项目内虚构资料',
    reference,
    recorded_at: '2026-09-30T10:00:00Z',
    summary: '样例记录提到，等候区里人多且声音较大。',
  };
}

/** 一条水合的助手消息。 */
export function hydratedAssistant(id: string, parts: HydratedMessage['parts']): HydratedMessage {
  return { id, role: 'assistant', parts };
}

/** 一条水合的使用者消息。 */
export function hydratedUser(id: string, text: string): HydratedMessage {
  return { id, role: 'user', parts: [{ type: 'text', text }] };
}

/** 水合响应。 */
export function historyResponse(messages: readonly HydratedMessage[]): ListMessagesResponse {
  return { session_id: 's1', messages: [...messages] };
}

/** 会话列表项。 */
export function sessionSummary(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    session_id: 's1',
    title: '等候时的沟通',
    support_object_name: '虚构对象',
    updated_at: '2026-09-30T10:00:00Z',
    last_message_preview: '可以试试减少人数',
    ...overrides,
  };
}

/** 事件序列的便捷类型（测试里显式列出期望的映射行）。 */
export type ScriptedStream = readonly RunEvent[];
