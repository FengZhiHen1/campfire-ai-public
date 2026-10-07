// 镜头相机:提供**有实际幅度**的运镜曲线,避免「缓慢微动」。
//
// ★ 为什么需要这个模块(踩过两次的坑):
//   第 1 次:我在静止段上加「缓慢连续微动」(每帧位移约 0.05px)→ 运动量指标不降反升
//           (帧差测不出,观众也看不出)—— 那是更精致的拖沓,不是节奏。
//   第 2 次:组件化改写时我把推近写成 1.00→1.14 铺满 36 秒 → 每帧约 0.0001,
//           同样测不出,S5 静止率飙到 98%。
//   结论:相机的**单位时间位移**必须可见。参考值:
//     · 推近:每 30 帧至少 0.02(即 1.0→1.06/秒 量级)
//     · 横移:每 30 帧至少 12px
//     · 节拍:任意连续 20 帧内应有一次离散事件(文字落位/状态切换/切镜)
//
// 本模块把这些参考值固化成一个「带节拍的推近」:基础推近 + 周期性呼吸位移,
// 保证任意 20 帧窗口内都有可见变化,同时不显得抖。
import {Easing, interpolate} from 'remotion';

export interface CameraState {
  scale: number;
  tx: number;
  ty: number;
}

/**
 * 带节拍的推近。
 *
 * @param frame 当前帧
 * @param from 起始缩放
 * @param to 终止缩放(建议 ≥ from + 0.06,否则每秒位移不可见)
 * @param duration 总帧数
 * @param opts.beat 节拍幅度(px):周期性横纵位移,默认 10
 * @param opts.beatPeriod 节拍周期(帧),默认 34
 */
export function pushCamera(
  frame: number,
  from: number,
  to: number,
  duration: number,
  opts: {beat?: number; beatPeriod?: number} = {},
): CameraState {
  const {beat = 10, beatPeriod = 34} = opts;
  const scale = interpolate(frame, [0, duration], [from, to], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.linear,
  });
  // 周期位移:让相机始终有可见的横向/纵向漂移(不是静止)
  const phase = (frame / beatPeriod) * Math.PI * 2;
  return {scale, tx: Math.sin(phase) * beat, ty: Math.cos(phase * 0.7) * beat * 0.6};
}

/**
 * 分段推近:把整段拆成若干「推近阶」,每阶之间有小停顿 —— 像真人在操作相机。
 *
 * @param stops 各阶的目标缩放(数组),长度 ≥ 2
 * @param cues 各阶的起始帧(与 stops 等长;第一项通常为 0)
 */
export function stagedPush(frame: number, stops: readonly number[], cues: readonly number[]): number {
  if (stops.length !== cues.length || stops.length < 2) {
    throw new Error('stagedPush: stops 与 cues 必须等长且至少两项');
  }
  const frames = cues.map((c, i) => (i === cues.length - 1 ? cues[cues.length - 1] + 1 : cues[i + 1]));
  return interpolate(frame, frames, [...stops], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.25, 1),
  });
}

/**
 * 节拍脉冲:在给定 cue 帧处产生一次快速上升再回落(用于强调「某个事件发生了」)。
 *
 * @param cue 事件帧
 * @param rise 上升帧数(默认 6)
 * @param fall 回落帧数(默认 14)
 */
export function beatPulse(frame: number, cue: number, rise = 6, fall = 14, peak = 1): number {
  const up = interpolate(frame, [cue, cue + rise], [0, peak], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.2, 0.75, 0.3, 1),
  });
  const down = interpolate(frame, [cue + rise, cue + rise + fall], [0, peak], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.5, 1),
  });
  return frame < cue + rise ? up : peak - down;
}
