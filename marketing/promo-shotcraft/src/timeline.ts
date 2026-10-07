// 帧级时间轴唯一真源(与 DESIGN_SPEC 九段分镜表一一对应)。
// SHOTS 是唯一事实源——字幕/SFX/转场全部从它派生。
//
// 2026-10-06 v4:145s。相比 v3(151s)的结构调整:
//   包装段(S1/S2/S3/S9)合计 10s → 5.7s;S7 28s → 22s;S8 14s → 10s
//   让出的时间全部给核心演示:S5 30s → 36s,S4 保持 26s(采集=用户如何使用)
//
// 2026-10-07 v16:175s。用户两条要求的合并落地:
//   ① 「时长不够 3 分钟」→ 扩到 175s(仍在 LIGHT 的 3 分钟内)
//   ② 「很多环节显得拖沓,把拖沓的时间给核心功能演示」→ **新增的时间全部给演示段**
//   包装段合计 21s → 28s(只 +7s,且 S1 从 3s→4s 只为让品牌 hold 更从容);
//   演示段合计 124s → 147s(占全片 84%)。
//   因此本表与「175s 九段」的目标规格在**总时长**上一致,在**分配**上故意偏演示 ——
//   分配依据是用户后一条更具体的反馈。
//
// 硬约束(两条,均由运动量脚本验收):
//   1. 任意连续 30 帧(1s)窗口内至少一次可见事件——硬切 / 文字落位 / 状态切换 / 大幅滚动。
//      连续缓动(每秒位移不足 1px)不算事件:帧差测不出,观众也看不出——那就是拖沓。
//   2. 静止只允许出现在:关键信息落位后的呼吸(≤1.5s)与品牌落定(≥1s,见 final-review B3)。

export const FPS = 30;

export interface Shot {
  id: string;
  from: number;
  duration: number;
  label: string;
}

export const SHOTS: Shot[] = [
  {id: 'S1', from: 0, duration: 120, label: '品牌开场'}, // 4s
  {id: 'S2', from: 120, duration: 180, label: '痛点情境'}, // 6s
  {id: 'S3', from: 300, duration: 240, label: '产品定位与首页'}, // 8s
  {id: 'S4', from: 540, duration: 960, label: '应急入口与八项采集'}, // 32s
  {id: 'S5', from: 1500, duration: 1200, label: 'AI 流式分析'}, // 40s ★核心
  {id: 'S6', from: 2700, duration: 1080, label: '行动卡'}, // 36s
  {id: 'S7', from: 3780, duration: 780, label: '记忆与档案'}, // 26s
  {id: 'S8', from: 4560, duration: 390, label: '案例库'}, // 13s
  {id: 'S9', from: 4950, duration: 300, label: '边界与收尾'}, // 10s
] as const;

export const TOTAL = SHOTS.reduce((end, s) => Math.max(end, s.from + s.duration), 0);

export function shot(id: string): Shot {
  const s = SHOTS.find((x) => x.id === id);
  if (!s) throw new Error(`SHOTS 无此镜头: ${id}`);
  return s;
}

/**
 * 画面上的字卡文案索引（不是字幕轨 —— 本片**无旁白、无字幕轨**，按用户要求
 * 「先完成无旁白版本」。这里只是「哪句话出现在哪一段」的索引，方便查证与改文案）。
 *
 * ★ v16 修正：原表列了 S7 的「它不替你决定什么是真的」，但那一句**从未出现在画面上**
 *   ——S7 的说明区实际写的是「档案只收你直接说过或确认过的内容」。
 *   一张记录与实现不符的索引表比没有更糟：它会让人以为画面里有这句话。
 *   现在每一条都与镜头源码里的字符串逐字对应（S2/S9 已验证）。
 */
export const CAPTIONS: {shotId: string; text: string}[] = [
  {shotId: 'S2', text: '照护一个孤独症孩子,最难的不是辛苦,是没人商量'},
  {shotId: 'S9', text: '不替代医生、不替代专业服务'},
];
