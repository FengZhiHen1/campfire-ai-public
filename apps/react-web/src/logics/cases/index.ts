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
export { useCaseListPage } from './hooks/useCaseListPage';
export { useCaseDetailPage } from './hooks/useCaseDetailPage';
export { useNarrativeSubmit } from './hooks/useNarrativeSubmit';
export { useExtractionResult } from './hooks/useExtractionResult';
export { useReviewPage } from './hooks/useReviewPage';
export { useCaseCardDetail } from './hooks/useCaseCardDetail';

// ---- 类型 ----
export type {
  NarrativeListItem,
  NarrativeDetail,
  CardSummary,
} from './types';

export type { CardData } from './services/cardApi';


// ---- 常量 ----
export {
  STATUS_TEXT_MAP,
  STATUS_CLASS_MAP,
  SOURCE_LABEL_MAP,
  CARD_STATUS_MAP,
  BEHAVIOR_TYPE_OPTIONS,
  BEHAVIOR_TYPE_VALUES,
  BEHAVIOR_DISPLAY_MAP,
  BEHAVIOR_FILTER_OPTIONS,
  SEVERITY_OPTIONS,
  SEVERITY_VALUES,
  SCENE_OPTIONS,
  SCENE_VALUES,
  EVIDENCE_LEVEL_OPTIONS,
  EVIDENCE_LEVEL_VALUES,
  FAMILY_CATEGORY_OPTIONS,
  SOURCE_TYPE_OPTIONS,
} from './types/constants';
