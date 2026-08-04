/**
 * 应急咨询域类型（ADR-009 时刻分层）。
 * 与后端 py_schemas.emergency / streaming 契约对齐。
 */

/** 行为桶（值与后端 BehaviorBucket 中文持久化值一致） */
export enum BehaviorBucket {
  MELTDOWN = '情绪崩溃',
  STEREOTYPY = '刻板行为',
  SELF_INJURY = '自伤',
  AGGRESSION = '攻击',
  ELOPEMENT = '走失',
  MEDICATION = '用药相关',
  SOCIAL_WITHDRAWAL = '社交退缩',
  HYPERACTIVITY = '多动',
  OTHER = '其他',
}

export const BUCKET_UI_LABELS: Record<BehaviorBucket, string> = {
  [BehaviorBucket.MELTDOWN]: '情绪哭闹',
  [BehaviorBucket.STEREOTYPY]: '刻板升级',
  [BehaviorBucket.SELF_INJURY]: '自伤',
  [BehaviorBucket.AGGRESSION]: '攻击',
  [BehaviorBucket.ELOPEMENT]: '走失',
  [BehaviorBucket.MEDICATION]: '用药',
  [BehaviorBucket.SOCIAL_WITHDRAWAL]: '社交退缩',
  [BehaviorBucket.HYPERACTIVITY]: '多动',
  [BehaviorBucket.OTHER]: '其他',
};

/** 红线桶（点选即高危） */
export const REDLINE_BUCKETS: ReadonlySet<BehaviorBucket> = new Set([
  BehaviorBucket.SELF_INJURY,
  BehaviorBucket.AGGRESSION,
  BehaviorBucket.ELOPEMENT,
  BehaviorBucket.MEDICATION,
]);

// === 消息模型（统一聊天容器，分级样式） ===

export interface SafetyCardPayload {
  card_id: string;
  bucket: string | null;
  stage: string | null;
  title: string;
  content: string;
  personalized: boolean;
  variant: 'normal' | 'redline' | 'elopement';
}

export interface StageQuestionPayload {
  question_id: string;
  question: string;
  options: string[];
  stage: string | null;
}

export interface RedlineGuidePayload {
  card: SafetyCardPayload;
  guidance: string;
  gate_trigger: string;
}

export interface FallbackNoticePayload {
  signal: string;
  message: string;
  guidance: string;
}

export interface EmergencyPlanPayload {
  immediate_action: string;
  soothing_script: string;
  observation: string;
  medical_judgment: string;
  sources: Array<{ case_id: string | null; title: string; source_type: string }>;
  disclaimer: string;
}

/** 聊天容器消息（分级样式：critical 大字号强视觉 / normal 常规） */
export type ConsultMessage =
  | { kind: 'safety_card'; id: string; card: SafetyCardPayload }
  | { kind: 'stage_question'; id: string; question: StageQuestionPayload }
  | { kind: 'redline_guide'; id: string; guide: RedlineGuidePayload }
  | { kind: 'plan_chunk'; id: string; text: string }
  | { kind: 'plan_result'; id: string; plan: EmergencyPlanPayload }
  | { kind: 'fallback_notice'; id: string; notice: FallbackNoticePayload }
  | { kind: 'user_answer'; id: string; text: string };

export type ConsultPhase =
  | 'bucket_select'   // 桶选择
  | 'stage_qa'        // 阶段问答
  | 'generating'      // 方案生成中
  | 'followup'        // 追问轮
  | 'redline'         // 红线锁定
  | 'done';           // 完成
