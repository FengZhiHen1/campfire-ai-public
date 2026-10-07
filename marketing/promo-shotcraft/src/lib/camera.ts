// 镜头相机:只提供**单向、有理由**的运镜曲线。
//
// ★★ 2026-10-07 删除「周期漂移」(用户裁决,原话:「非常反人类」「没有任何语义」
//    「还会影响表现效果」)。本模块原有一个给整机叠加 sin/cos 周期位移的
//    `pushCamera(..., {beat, beatPeriod})`(±10～14px,约 1.1s 一圈)。它的存在
//    理由是**指标**:当时的静止率门禁要求「任意 20 帧窗口内必须有可见变化」,
//    于是用一段没有方向的连续漂移把帧差填满 —— 本期复核确认,那是为通过度量
//    而造的运动,不是叙事需要的运动(见 CHECKPOINT 的 P0 教训同型:度量写成了目标)。
//
// ★★ 2026-10-08 删除「全程线性推近」(用户裁决,原话:「我为什么还能看到手机框在动?
//    太不好看了」)。
//
//    原实现:每个设备镜头都调
//      `pushCamera(frame, 1.0, 1.2, duration)` → 一条 linear 曲线铺满**整段**
//      再与 `stagedPush` 取 `Math.max` ⇒ **任意一帧都在变大,全程没有一帧是静止的**。
//    为什么不好看:scale 加在 `DeviceStage` 外层,而那一层里是「外壳 + 屏幕」一起的
//      —— 于是**黑色边框、圆角、机身跟着一起放大**。观众看到的是「这台手机自己在
//      慢慢变大」,不是「镜头凑近去看」。前者像素材被拉伸,后者才是运镜。
//    做法:删除整段线性推近。运镜只保留 `stagedPush` —— 它是**分段**的:
//      每一阶对应叙事上的下一件事,阶与阶之间天然有停顿(此时画面完全静止),
//      所以「框在动」被限制在少数几个短窗口里,而不是全程。
//
//    代价与边界(如实登记):
//      · 各段因此出现「完全静止」的窗口(推近不再兜底)。这不是回归 ——
//        静止本来就该由**语义事件**(文字落位/滚动/流式输出)填,而不是由相机兜底;
//      · `bezelscan` 测的是「设备框到画布边的边距」,推近变小后边距变大,不影响判据;
//      · 若某段确实太静,正确做法是在该段补一个**有理由的分段推近阶**,而不是恢复全程曲线。
import {Easing, interpolate} from 'remotion';

export interface CameraState {
  scale: number;
}

/**
 * 单向推近(**有限窗口**,不再是整段)。
 *
 * ★ 2026-10-08 起,本函数不再被镜头直接调用来铺满整段(那正是用户否决的「框一直在动」)。
 *   它现在的用途:在某一段**明确需要凑近看**的窗口内做一次推近,窗口之外保持不动。
 *   调用方必须给出 `from`/`to` 帧 —— 不允许「整段线性」这种写法。
 *
 * @param frame 当前帧
 * @param from 起始缩放
 * @param to 终止缩放
 * @param window 推近发生的帧窗口 `[起, 止]`;窗口外 clamp 到两端(即静止)
 */
export function pushCamera(
  frame: number,
  from: number,
  to: number,
  window: readonly [number, number],
): CameraState {
  const scale = interpolate(frame, [window[0], window[1]], [from, to], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.25, 1),
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
 * ★★ 2026-10-08 修 off-by-one(这处此前会让每一阶的最后**单帧跳变**):
 *   原实现 `frames = cues.map((c, i) => i === last ? cues[last] + 1 : cues[i + 1])`
 *   把每个阶整体**后移一位**,并把最后一阶压成 `cues[last] → cues[last] + 1`
 *   ⇒ 最后一段只花 **1 帧**从上一阶跳到目标值。实测证据:`events.json` 里两条
 *   「相机可见跳变:stagedPush 末阶在一帧内 1.12→1.18 / 1.08→1.20」
 *   (S7 f4396、S8 f4873),`motion-gate` 的可见性检查也报过这两帧。
 *   一帧跳一次的框是最难看的动法 —— 而且它伪装成「推近阶」,不查代码看不出来。
 *   修法:关键帧直接用 `cues` 本身(含首项 0),于是每阶都是正常斜坡;
 *   末项补 `duration` 让最后一阶有完整的爬升区间,而不是 1 帧。
 *
 * @param stops 各阶的目标缩放(数组),长度 ≥ 2
 * @param cues 各阶的起始帧(与 stops 等长;第一项通常为 0)
 * @param duration 该镜头总帧数(用于给最后一阶一个真实的爬升区间)
 */
export function stagedPush(
  frame: number,
  stops: readonly number[],
  cues: readonly number[],
  duration: number,
): number {
  if (stops.length !== cues.length || stops.length < 2) {
    throw new Error('stagedPush: stops 与 cues 必须等长且至少两项');
  }
  const last = cues.length - 1;
  // 每个阶的区间 = [cues[i], cues[i+1]];最后一阶 = [cues[last], duration]
  const frames = [...cues.slice(0, last), Math.max(duration, cues[last] + 1)];
  return interpolate(frame, frames, [...stops], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.25, 1),
  });
}
