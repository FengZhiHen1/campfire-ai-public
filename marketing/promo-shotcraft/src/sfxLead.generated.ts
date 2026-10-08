// 实测表,勿手改 —— 数值由 public/audio/sfx/*.mp3 实测得出。
// ⚠ 2026-10-08：原负责生成/校验该表的 `verify/sfx-lead.py` 已删除（用户裁决：
//   闸门只保留 pytest/vitest）。该脚本**从来没有写操作**，只做「实测 vs 表内值」比对，
//   故本表在删除前就已无生成器——它是手工维护的实测结果。
//
// 两张表解决两个不同的问题(2026-10-08,用户前后两次报「音画不同步」后查清):
//
// ① SFX_LEAD_FRAMES —— **裁掉素材开头的静音**(<Audio trimBefore={...}>)。
//    素材不是从第 0 个样本就开始响:实测 16 个里 11 个开头有静音,最长 488ms
//    (data-stream)。不裁的话,声音实际响起的时刻 = cue 帧 + 静音长度,而每条
//    延迟不同 ⇒ 表现成「修了一处、别处又不对」。
//
// ② SFX_CUE_LEAD —— 把 cue 提前,使**可听起音**落在画面事件上。
//    裁掉静音后仍有落差:16 个素材里只有 3 个是瞬态(mech-lock/text-type/ui-pop),
//    其余是渐强扫过 —— 能量到 10% 还要 1–22 帧(sparkle 22 帧;whoosh-fast 14 帧)。
//    这一条量的是「裁静音之后,能量达到自身峰值 10% 还差几帧」,上限 10 帧。
//    为什么不用「到峰值」:whoosh/sparkle 的峰在 20–43 帧后,按峰值对齐会让声音
//    明显抢在画面前面 —— 那是把「晚」换成「早」,同样是不同步。
//
// 单位:帧(FPS=30)。
export const SFX_LEAD_FRAMES: Record<string, number> = {
  'camera-autofocus': 10,
  'click-camera': 3,
  'data-stream': 15,
  'impact-deep-whoosh': 4,
  'mech-lock': 0,
  'paper-sheet': 0,
  'riser-cine': 3,
  'sparkle-touch': 1,
  'sparkle': 9,
  'swoosh-quick': 2,
  'text-type': 0,
  'transition-snap': 1,
  'transition-soft': 3,
  'ui-pop': 0,
  'whoosh-big': 2,
  'whoosh-fast': 0,
};

/** 把 cue 提前的帧数,使可听起音落在画面事件上。规则见文件头。 */
export const SFX_CUE_LEAD: Record<string, number> = {
  'camera-autofocus': 0,
  'click-camera': 1,
  'data-stream': 0,
  'impact-deep-whoosh': 4,
  'mech-lock': 1,
  'paper-sheet': 3,
  'riser-cine': 3,
  'sparkle-touch': 5,
  'sparkle': 10,
  'swoosh-quick': 2,
  'text-type': 0,
  'transition-snap': 1,
  'transition-soft': 6,
  'ui-pop': 0,
  'whoosh-big': 10,
  'whoosh-fast': 10,
};
