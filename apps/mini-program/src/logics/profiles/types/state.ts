/**
 * PROF-07 档案数据逻辑 — 前端交互态联合类型
 *
 * 数据来源:
 *   - PROF-07 落地规范 §1.8: MUST — 状态机定义
 * 边界:
 *   - 依赖: 无
 *   - 被依赖: store/, hooks/, types/contracts.ts
 * 禁止行为:
 *   - 禁止将状态值用于后端 API 请求——这些是纯前端交互态
 */

/** 档案列表加载状态 */
export type ProfileListState = 'idle' | 'loading' | 'ready' | 'error';

/** 档案提交状态 */
export type ProfileSubmitState = 'idle' | 'submitting' | 'success' | 'error';

/** 微问卷交互态 */
export type MicroSurveyState = 'hidden' | 'showing' | 'answering' | 'submitted';

/** 干预有效性三档评价 */
export type InterventionFeedback = '有帮助' | '一般' | '无帮助';
