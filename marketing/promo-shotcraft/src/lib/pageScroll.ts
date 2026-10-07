// 页面滚动度量:把「滚动进度 0→1」映射成真实像素。
//
// ★ 为什么需要它(截图路线缺陷②的根治点):
//   截图路线的滚动量是写死的像素值,一旦超过内容高度就滑出画面露空白
//   (S8 实测滚到 1680 而该页 maxScroll 只有 1204)。
//   组件路线也不能猜:各页真实高度差很大
//   (首页 0 / 应急表单 344 / 档案 4194 / 案例库 1204)。
//
// 真源:src/page-metrics.json,由 capture/measure-page-metrics.mjs 在真实浏览器里量出。
// 重新量: node capture/measure-page-metrics.mjs
import METRICS from '../page-metrics.json';
import ELEMENTS from '../element-metrics.json';

export type PageKey = keyof typeof METRICS;

/**
 * 关键元素的实测位置(内容坐标系 offsetTop 与「把它滚到屏幕上方 1/4」所需的滚动像素)。
 *
 * 真源:src/element-metrics.json,由 capture/measure-element-positions.mjs 在真实浏览器里量出。
 * 重新量: node capture/measure-element-positions.mjs
 */
export function markScrollPx(page: 'cases' | 'profile', mark: string): number {
  const p = (ELEMENTS as Record<string, {maxScroll: number; marks: Record<string, {scrollPx: number}>}>)[page];
  return Math.max(0, p?.marks?.[mark]?.scrollPx ?? 0);
}

/** 关键元素在内容坐标系里的 offsetTop(用于判断「这个元素在页面哪个位置」)。 */
export function markOffsetTop(page: 'cases' | 'profile', mark: string): number {
  const p = (ELEMENTS as Record<string, {marks: Record<string, {offsetTop: number}>}>)[page];
  return Math.max(0, p?.marks?.[mark]?.offsetTop ?? 0);
}

/**
 * 某页的最大可滚动量(逻辑 px)。
 *
 * 前置: key 存在于 page-metrics.json
 * 后置: 返回 max(0, scrollHeight - clientHeight)
 * 异常: key 缺失时返回 0(不滚动,而不是猜一个值滚出去)
 */
export function maxScrollOf(key: PageKey): number {
  const m = METRICS[key] as {maxScroll?: number} | undefined;
  return Math.max(0, m?.maxScroll ?? 0);
}

/**
 * 把滚动进度(0→1)换算成像素。
 *
 * 进度会被**夹紧**在 [0,1]:少了这一步,曲线外推就会滚出内容底部 —— 那正是要修的形态。
 */
export function scrollProgress(key: PageKey, progress: number): number {
  const clamped = Math.min(1, Math.max(0, progress));
  return clamped * maxScrollOf(key);
}

/**
 * 滚动到某个具体内容位置的进度比例。
 *
 * 用途:镜头常常要「滚到某个区块」(如档案页的待确认分组、案例库的虚构样例条目)。
 * 直接给像素同样是猜;给比例则天然随内容高度变化 —— 内容变长时不会失效。
 *
 * @param key 页面
 * @param ratio 目标位置占全部可滚动量的比例(0=顶部,1=底部)
 */
export function scrollTo(key: PageKey, ratio: number): number {
  return scrollProgress(key, ratio);
}

export {METRICS};
