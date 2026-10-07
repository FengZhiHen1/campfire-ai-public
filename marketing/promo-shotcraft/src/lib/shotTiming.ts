// 镜头时长与节拍工具:让镜头内部的时间点**从自身时长派生**,而不是写死帧号。
//
// ★ 为什么需要(踩过的坑):
//   每个镜头原先用绝对帧号写时间点(如 `interpolate(frame, [30, 56], ...)`)。
//   一旦 timeline.ts 改了段长(145s→175s),这些帧号全部失配 ——
//   表现为:段尾还有 30 帧什么都不发生(拖沓),或某个动作被切在段外(看不到)。
//   改一次段长就要逐个镜头手改十几处帧号,且必然漏改。
//
//   改成比例派生后,段长变化自动跟随:所有 `at(0.5)` 永远是「这一段的中间」。
//
// 用法:
//   const t = useShotTiming();          // 取本镜头在 Composition 里的时长
//   interpolate(frame, t.span(0.2, 0.5), [0, 1])   // 20%→50% 处完成
//   t.at(0.35)                          // 单点:35% 处
import {useVideoConfig} from 'remotion';

export interface ShotTiming {
  /** 本镜头的总帧数 */
  duration: number;
  /** 单点:把比例换算成帧号(夹在段内) */
  at: (ratio: number) => number;
  /** 区间:把一对比例换算成帧号区间(供 interpolate 用) */
  span: (from: number, to: number) => [number, number];
}

/**
 * 取当前镜头的时长并把比例换算成帧号。
 *
 * 前置: 组件必须渲染在 <Sequence durationInFrames={...}> 或 Composition 里
 * 后置: at/span 输出的帧号都落在 [0, duration] 内
 * 异常: 无
 *
 * 注:用 useVideoConfig().durationInFrames —— 在 Sequence 内它是**该 Sequence 的**
 * 时长,因此镜头不需要知道自己在全片的位置,只按自己的比例排布。
 */
export function useShotTiming(): ShotTiming {
  const {durationInFrames} = useVideoConfig();
  const clamp = (n: number) => Math.max(0, Math.min(durationInFrames, Math.round(n)));
  return {
    duration: durationInFrames,
    at: (ratio) => clamp(ratio * durationInFrames),
    span: (from, to) => [clamp(from * durationInFrames), clamp(to * durationInFrames)],
  };
}
