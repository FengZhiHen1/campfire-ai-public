// 全片时间线唯一真源,秒数与 screenplay/narration.md 二稿段预算一一对应。
// 改段长先改脚本,再同步此处;Root.tsx 的 duration 与 Main.tsx 的 Sequence 都由它派生。

export const FPS = 30;

export const SEGMENTS = [
  {id: 'S1', label: '痛点开场', sec: 18},
  {id: 'S2', label: '产品定位', sec: 12},
  {id: 'S3', label: '应急咨询', sec: 62},
  {id: 'S4', label: '记忆与档案', sec: 40},
  {id: 'S5', label: '案例库', sec: 12},
  {id: 'S6', label: '边界与收尾', sec: 31},
] as const;

export type SegmentId = (typeof SEGMENTS)[number]['id'];

const withFrames = SEGMENTS.map((s) => ({...s, frames: s.sec * FPS}));

export const START: Record<SegmentId, number> = withFrames.reduce(
  (acc, s, i) => ({
    ...acc,
    [s.id]: withFrames.slice(0, i).reduce((n, x) => n + x.frames, 0),
  }),
  {} as Record<SegmentId, number>,
);

export const DUR: Record<SegmentId, number> = withFrames.reduce(
  (acc, s) => ({...acc, [s.id]: s.frames}),
  {} as Record<SegmentId, number>,
);

export const TOTAL_FRAMES = withFrames.reduce((n, s) => n + s.frames, 0);
