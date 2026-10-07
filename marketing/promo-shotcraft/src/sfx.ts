// SFX 钉帧表:声明式集中管理。
//
// ── v16 的关键改动:cue 从「绝对帧偏移」改为「本镜头内的比例」 ──────────────
//   旧写法 `shot('S4').from + 120` 是绝对偏移。段长从 780f 扩到 960f 后,
//   这个偏移不再落在「勾选第 1 项」那一帧上 —— 音效与画面事件脱钩,
//   听感变成「声音乱响、和动作对不上」。而这类失配是**静默的**:
//   check-sfx.ts 只能验证「cue 在镜头区间内」,验证不了「cue 落在正确的动作上」。
//
//   改成比例后,cue 跟着画面走:镜头内部的时间点本身也是比例派生的
//   (见 lib/shotTiming.ts),两边用同一套比例即自动对齐。
//
// 词汇:whoosh(运镜)/impact(落地)/riser(铺垫)/sparkle(光效)/transition(转场)。
//
// SFX 规则(由 scripts/check-sfx.ts 机械校验):
//   ① 每条 from 必须落在其所属镜头区间内;
//   ② 长样本(带 durationInFrames)不得超出镜头或全片末尾;
//   ③ 每段至少 2 条,避免出现哑段;
//   ④ 节拍对齐画面事件(字标落定、切题、检索命中、闸门点亮)。
import {SHOTS, shot} from './timeline';
import type {Shot} from './timeline';

export interface SfxEntry {
  from: number;
  src: string;
  volume: number;
  comment: string;
  /** 长样本(>5s)必须显式截断,帧数 */
  durationInFrames?: number;
}

/**
 * 把「镜头 + 比例」换算成绝对帧号。
 *
 * 前置: ratio ∈ [0,1];超出会被夹到 [0,1](避免 cue 落到别的镜头里)
 * 后置: 返回落在该镜头区间内的绝对帧号
 * 异常: 镜头 id 不存在时 shot() 抛错(与旧写法一致)
 */
function at(shotId: string, ratio: number): number {
  const s: Shot = shot(shotId);
  const r = Math.min(1, Math.max(0, ratio));
  return s.from + Math.round(r * s.duration);
}

/** 需要镜头时长时用它(如「倒数若干帧」的场景)。 */
export {SHOTS};

export const SFX: SfxEntry[] = [
  // ── S1 品牌开场(4s)──
  {from: at('S1', 0.11), src: 'transition-soft', volume: 0.4, durationInFrames: 42, comment: 'S1 字标压印落定'},
  {from: at('S1', 0.8), src: 'whoosh-fast', volume: 0.7, durationInFrames: 20, comment: 'S1 消散交棒'},

  // ── S2 痛点情境(6s)──
  {from: at('S2', 0.05), src: 'transition-soft', volume: 0.28, durationInFrames: 40, comment: 'S2 情境首行'},
  {from: at('S2', 0.62), src: 'sparkle-touch', volume: 0.26, comment: 'S2 转折线展开'},
  // ★ 末行「是没人商量」落在 0.72(不是 0.62 —— 0.62 是转折线)。
  //   这条曾按旧时间轴的绝对帧偏移 +88 落在转折线上,与画面事件脱钩。
  {from: at('S2', 0.73), src: 'impact-deep-whoosh', volume: 0.34, durationInFrames: 30, comment: 'S2「是没人商量」强调'},

  // ── S3 定位与首页(8s)──
  {from: at('S3', 0.02), src: 'whoosh-big', volume: 0.45, durationInFrames: 50, comment: 'S3 设备框浮入'},
  {from: at('S3', 0.22), src: 'sparkle-touch', volume: 0.32, comment: 'S3 卖点1 点亮'},
  {from: at('S3', 0.33), src: 'sparkle-touch', volume: 0.32, comment: 'S3 卖点2 点亮'},
  {from: at('S3', 0.44), src: 'sparkle-touch', volume: 0.34, comment: 'S3 卖点3 点亮'},
  {from: at('S3', 0.7), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S3 定位主句'},

  // ── S4 应急入口与八项采集(32s)──
  // 比例与 S4Intake.tsx 的四段划分一致:入口 0-0.13 / 第1题 0.13-0.36 / 快掠 0.36-0.62 / 自由文本 0.62-1
  {from: at('S4', 0.045), src: 'camera-autofocus', volume: 0.45, durationInFrames: 90, comment: 'S4 高亮圈锁定应急入口'},
  {from: at('S4', 0.13), src: 'transition-soft', volume: 0.32, durationInFrames: 34, comment: 'S4 进入第 1 题'},
  {from: at('S4', 0.16), src: 'click-camera', volume: 0.42, comment: 'S4 勾选「明显疼痛」'},
  // 快掠:四道题各一次切题音(比例均分 0.36→0.62)
  {from: at('S4', 0.38), src: 'click-camera', volume: 0.4, comment: 'S4 快掠 第3题'},
  {from: at('S4', 0.44), src: 'click-camera', volume: 0.38, comment: 'S4 快掠 第4题'},
  {from: at('S4', 0.5), src: 'click-camera', volume: 0.36, comment: 'S4 快掠 第5题'},
  {from: at('S4', 0.56), src: 'click-camera', volume: 0.34, comment: 'S4 快掠 第6题'},
  // 自由文本段:打字声 + 提交
  {from: at('S4', 0.66), src: 'text-type', volume: 0.36, durationInFrames: 60, comment: 'S4 写下现场的样子'},
  {from: at('S4', 0.93), src: 'ui-pop', volume: 0.5, comment: 'S4 按下「提交，开始分析」'},

  // ── S5 AI 流式分析(40s)—— 全片核心 ──
  {from: at('S5', 0.004), src: 'transition-soft', volume: 0.32, durationInFrames: 40, comment: 'S5 分析段切入'},
  {from: at('S5', 0.025), src: 'data-stream', volume: 0.28, durationInFrames: 60, comment: 'S5「正在分析」底噪'},
  {from: at('S5', 0.077), src: 'text-type', volume: 0.34, durationInFrames: 50, comment: 'S5 首句结论流出'},
  {from: at('S5', 0.178), src: 'click-camera', volume: 0.35, comment: 'S5 资料1 命中'},
  {from: at('S5', 0.21), src: 'click-camera', volume: 0.33, comment: 'S5 资料2 命中'},
  {from: at('S5', 0.245), src: 'transition-soft', volume: 0.28, durationInFrames: 40, comment: 'S5 判据读完'},
  {from: at('S5', 0.3), src: 'sparkle-touch', volume: 0.34, comment: 'S5 档案组带入 1-2'},
  {from: at('S5', 0.36), src: 'sparkle-touch', volume: 0.32, comment: 'S5 档案组带入 3-4'},
  {from: at('S5', 0.42), src: 'impact-deep-whoosh', volume: 0.36, durationInFrames: 40, comment: 'S5 医疗红灯优先于孤独症解释'},
  {from: at('S5', 0.47), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S5 六层闸门逐层'},
  {from: at('S5', 0.52), src: 'click-camera', volume: 0.34, comment: 'S5 闸门 2'},
  {from: at('S5', 0.57), src: 'click-camera', volume: 0.34, comment: 'S5 闸门 3'},
  {from: at('S5', 0.62), src: 'click-camera', volume: 0.33, comment: 'S5 闸门 4'},
  {from: at('S5', 0.67), src: 'click-camera', volume: 0.33, comment: 'S5 闸门 5'},
  {from: at('S5', 0.72), src: 'click-camera', volume: 0.32, comment: 'S5 闸门 6'},
  {from: at('S5', 0.77), src: 'sparkle-touch', volume: 0.36, comment: 'S5 未预存组标注'},
  {from: at('S5', 0.82), src: 'camera-autofocus', volume: 0.36, durationInFrames: 90, comment: 'S5 收束到结论'},
  {from: at('S5', 0.9), src: 'transition-soft', volume: 0.3, durationInFrames: 46, comment: 'S5 交棒行动卡'},
  {from: at('S5', 0.96), src: 'whoosh-fast', volume: 0.5, durationInFrames: 22, comment: 'S5 段落收尾'},

  // ── S6 行动卡(36s)──
  {from: at('S6', 0.02), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S6 三档特写切入'},
  {from: at('S6', 0.055), src: 'sparkle-touch', volume: 0.38, comment: 'S6「稳定」点亮'},
  {from: at('S6', 0.095), src: 'sparkle-touch', volume: 0.4, comment: 'S6「未排除」点亮'},
  {from: at('S6', 0.135), src: 'sparkle-touch', volume: 0.44, comment: 'S6「高风险」点亮'},
  {from: at('S6', 0.24), src: 'whoosh-fast', volume: 0.55, durationInFrames: 24, comment: 'S6 交棒设备框'},
  {from: at('S6', 0.3), src: 'impact-deep-whoosh', volume: 0.4, durationInFrames: 34, comment: 'S6 行动卡落定'},
  {from: at('S6', 0.37), src: 'text-type', volume: 0.3, durationInFrames: 50, comment: 'S6 建议逐条'},
  {from: at('S6', 0.44), src: 'camera-autofocus', volume: 0.4, durationInFrames: 90, comment: 'S6 来源标注高亮'},
  {from: at('S6', 0.56), src: 'click-camera', volume: 0.33, comment: 'S6 来源条 2'},
  {from: at('S6', 0.66), src: 'click-camera', volume: 0.33, comment: 'S6 来源条 3'},
  {from: at('S6', 0.76), src: 'click-camera', volume: 0.32, comment: 'S6 来源条 4'},
  {from: at('S6', 0.86), src: 'transition-soft', volume: 0.32, durationInFrames: 46, comment: 'S6 双会话对照落位'},

  // ── S7 记忆与档案(26s)──
  {from: at('S7', 0.01), src: 'whoosh-big', volume: 0.4, durationInFrames: 44, comment: 'S7 档案页浮入'},
  {from: at('S7', 0.08), src: 'sparkle-touch', volume: 0.3, comment: 'S7 摘要字段 1'},
  {from: at('S7', 0.2), src: 'sparkle-touch', volume: 0.3, comment: 'S7 摘要字段 2'},
  {from: at('S7', 0.34), src: 'whoosh-fast', volume: 0.42, durationInFrames: 24, comment: 'S7 滚向待确认分组'},
  {from: at('S7', 0.62), src: 'camera-autofocus', volume: 0.42, durationInFrames: 90, comment: 'S7 高亮圈锁定确认按钮'},
  {from: at('S7', 0.85), src: 'ui-pop', volume: 0.48, comment: 'S7 确认状态翻转'},

  // ── S8 案例库(13s)──
  {from: at('S8', 0.02), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S8 案例库切入'},
  {from: at('S8', 0.45), src: 'whoosh-fast', volume: 0.4, durationInFrames: 24, comment: 'S8 滚向虚构样例'},
  {from: at('S8', 0.8), src: 'sparkle-touch', volume: 0.42, comment: 'S8 虚构样例标签点亮'},

  // ── S9 边界与收尾(10s)──
  {from: at('S9', 0.02), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S9 边界声明第一句'},
  {from: at('S9', 0.1), src: 'sparkle-touch', volume: 0.26, comment: 'S9 第二句'},
  {from: at('S9', 0.19), src: 'sparkle-touch', volume: 0.26, comment: 'S9 第三句'},
  {from: at('S9', 0.43), src: 'riser-cine', volume: 0.38, durationInFrames: 90, comment: 'S9 riser 品牌组装段起'},
  {from: at('S9', 0.63), src: 'impact-deep-whoosh', volume: 0.45, durationInFrames: 60, comment: 'S9 字标 stamp 落地(全片峰值)'},
  {from: at('S9', 0.73), src: 'sparkle', volume: 0.3, durationInFrames: 40, comment: 'S9 rule 长出余韵'},
  {from: at('S9', 0.76), src: 'sparkle-touch', volume: 0.26, comment: 'S9 光扫掠过'},
  // 渐隐收束:放在段尾但**留出样本自身时长**,否则会越过全片末尾(曾被 check-sfx 抓出)
  {from: at('S9', 0.85), src: 'transition-soft', volume: 0.28, durationInFrames: 40, comment: 'S9 渐隐收束'},
];
