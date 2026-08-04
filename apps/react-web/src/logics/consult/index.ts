/**
 * 应急咨询域入口（ADR-009 时刻分层）。
 *
 * consult 域的唯一公共接口。View 层只能通过此入口导入。
 */

// ---- Hook（View 层主通道）----
export { useConsultSession } from './hooks/useConsultSession';

// ---- API 服务（历史/详情页独立使用）----
export { consultApi } from './services/consultApi';
export type { ConsultHistoryItem, ConsultHistoryList } from './services/consultApi';

// ---- 类型 ----
export { BehaviorBucket, BUCKET_UI_LABELS, REDLINE_BUCKETS } from './types';
export type {
  ConsultMessage,
  ConsultPhase,
  EmergencyPlanPayload,
  FallbackNoticePayload,
  RedlineGuidePayload,
  SafetyCardPayload,
  StageQuestionPayload,
} from './types';
