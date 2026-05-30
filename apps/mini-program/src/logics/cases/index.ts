/**
 * CASE-09 案例管理逻辑 — 域入口。
 *
 * cases 域的唯一公共接口。View 层只能通过此入口导入，
 * 禁止直接引用 hooks/、store/、services/ 下的内部文件。
 *
 * 域内分层：
 *   views/ → hooks/ → store/ (Zustand) / services/ (API)
 */

// ---- Hooks（View 层唯一合法通道）----
export { useCaseList } from './hooks/useCaseList';
export { useCaseDetail } from './hooks/useCaseDetail';
export { useCaseFormStore } from './hooks/useCaseFormStore';
export { useCaseListPage } from './hooks/useCaseListPage';
export { useCaseDetailPage } from './hooks/useCaseDetailPage';
export { useCaseSubmit } from './hooks/useCaseSubmit';
export { useNarrativeSubmit } from './hooks/useNarrativeSubmit';
export { useExtractionResult } from './hooks/useExtractionResult';

// ---- 类型 ----
export type {
  CaseFormFields,
  CaseFormState,
  FormErrors,
  NarrativeListItem,
  NarrativeDetail,
  NarrativeListResponse,
  CardSummary,
} from './types';

export type { UseCaseListParams, UseCaseListReturn } from './hooks/useCaseList';
export type { UseCaseDetailReturn } from './hooks/useCaseDetail';
export type { UseCaseListPageReturn } from './hooks/useCaseListPage';
export type { UseCaseDetailPageReturn } from './hooks/useCaseDetailPage';
export type { UseCaseSubmitReturn } from './hooks/useCaseSubmit';
export type { UseNarrativeSubmitReturn } from './hooks/useNarrativeSubmit';
export type { UseExtractionResultReturn } from './hooks/useExtractionResult';

// ---- 常量 ----
export {
  STATUS_TEXT_MAP,
  STATUS_CLASS_MAP,
  SOURCE_LABEL_MAP,
  CARD_STATUS_MAP,
  BEHAVIOR_TYPE_OPTIONS,
  SEVERITY_OPTIONS,
  SCENE_OPTIONS,
  EVIDENCE_LEVEL_OPTIONS,
  FAMILY_CATEGORY_OPTIONS,
  SOURCE_TYPE_OPTIONS,
} from './types/constants';
