// 镜头相机:只提供**单向、有理由**的运镜曲线。
//
// ★★ 2026-10-07 删除「周期漂移」(用户裁决,原话:「非常反人类」「没有任何语义」
//    「还会影响表现效果」)。本模块原有一个给整机叠加 sin/cos 周期位移的
//    `pushCamera(..., {beat, beatPeriod})`(±10～14px,约 1.1s 一圈)。它的存在
//    理由是**指标**:当时的静止率门禁要求「任意 20 帧窗口内必须有可见变化」,
//    于是用一段没有方向的连续漂移把帧差填满 —— 本期复核确认,那是为通过度量
//    而造的运动,不是叙事需要的运动(见 CHECKPOINT 的 P0 教训同型:度量写成了目标)。
//
//   现在的纪律(与 src/events.json、verify/motion-gate.py 配套):
//     · 连续运动只允许**单向、有叙事理由**的推近/横移(凑近看、逐段进入下一件事);
//     · 需要「画面活着」时用**离散语义事件**(文字落位/状态切换/滚动刹车/流式输出),
//       而不是无方向的漂移;
//     · 门禁不再要求「任意窗口都有像素变化」,而是要求「任意 ≤2s 窗口内有语义事件,
//       且声明的 hold 真的静止」——两边都要能被测量证伪。
import {Easing, interpolate} from 'remotion';

export interface CameraState {
  scale: number;
}

/**
 * 单向推近。
 *
 * @param frame 当前帧
 * @param from 起始缩放
 * @param to 终止缩放
 * @param duration 总帧数
 *
 * 为什么没有横向/纵向分量:相机位移必须由叙事给出方向。若某个镜头确实需要
 * 横移,应当把它写成一段有起止意图的横移(如「跟随」),而不是给所有镜头叠一层
 * 周期抖动 —— 后者正是被用户否决的那个做法。
 */
export function pushCamera(frame: number, from: number, to: number, duration: number): CameraState {
  const scale = interpolate(frame, [0, duration], [from, to], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.linear,
  });
  return {scale};
}

/**
 * 分段推近:把整段拆成若干「推近阶」,每阶之间有小停顿 —— 像真人在操作相机。
 *
 * 这是**语义**运动:每一阶对应叙事上的一个新对象(下一道题、下一节卡片、
 * 待确认分组…),所以它保留。与已删除的周期漂移的区别在于:它单调、有终点、
 * 与事件对齐。
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
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.25, 1),
  });
}
