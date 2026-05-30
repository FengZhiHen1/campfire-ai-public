/**
 * CSLT-08 咨询编排逻辑 — 域入口。
 *
 * consult 域的唯一公共接口。View 层只能通过此入口导入，
 * 禁止直接引用 hooks/、store/、services/ 下的内部文件。
 *
 * 域内分层：
 *   views/ → hooks/ → store/ (Zustand) / services/ (API + SSE)
 */

// ---- Hook（View 层唯一合法通道）----
export { useConsult } from './hooks/useConsult';

// ---- 类型 ----
export type {
  UseConsultReturn,
  ConsultSessionState,
  ConsultSessionStateData,
  ConsultErrorCode,
  ConsultInputState,
  ConsultSubmitRequest,
  BehaviorTypeCategory,
  CrisisLevel,
  EmotionLevel,
  PlanSection,
  StructuredPlan,
  TicketGuide,
  TicketRiskLevel,
  MessageItem,
  MessageId,
  MessageSender,
  MessageType,
  ReferencedCase,
  StreamErrorCode,
  ValidationVerdict,
  ConfidenceValidationOutput,
  ConsultationHistoryListItem,
  ConsultationHistoryDetail,
  ConsultationHistoryCreate,
  ChunkEventPayload,
  DoneEventPayload,
  ErrorEventPayload,
} from './types';

export { StateTransitionError } from './types';

// ---- 品牌类型 ----
export type { SessionId, RequestId } from './consult.contract';

// ---- 类型守卫 ----
export { isValidConsultSubmitRequest, isValidBehaviorDescription } from './consult.contract';
