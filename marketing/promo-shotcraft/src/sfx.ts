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

  // ── S5 AI 流式分析(26s)—— 全片核心 ──
  //
  // ★★ 2026-10-08 重钉(用户报告「59s 开始音画不同步」)。
  //   原因:S5 被重写为「展开思考区 → 真实推理流出 → 收起 → 判断句 → 依据线 → 行动卡到场」,
  //   但这 19 条音效**仍钉在旧 S5 的节拍上**(注释写的是「资料1/2 命中」「档案组带入 1-2/3-4」
  //   「六层闸门逐层 + 闸门 2…6」「未预存组标注」「收束到结论」)—— 那些离散视觉事件在新 S5 里
  //   **已经不存在**。最刺眼的一条是 `at('S5', 0.9)` 注释写「交棒行动卡」,而卡片实际在
  //   `CARD_IN_R = 0.63` 就出现了 ⇒ 那声 whoosh 晚了 (0.9-0.63)×26s = **7.0 秒**,
  //   正落在用户听到不同步的 59s 一带(S5 从 36s 起,0.9 ⇒ 59.4s)。
  //   现在每一条都对齐 S5Analysis.tsx 里真实存在的时刻(比例同源,段长再变会自动跟随)。
  {from: at('S5', 0.004), src: 'transition-soft', volume: 0.32, durationInFrames: 40, comment: 'S5 分析段切入'},
  {from: at('S5', 0.02), src: 'data-stream', volume: 0.28, durationInFrames: 60, comment: 'S5「正在分析…」底噪'},
  {from: at('S5', 0.05), src: 'ui-pop', volume: 0.34, comment: 'S5 展开思考区(使用者的一次动作)'},
  {from: at('S5', 0.075), src: 'text-type', volume: 0.32, durationInFrames: 50, comment: 'S5 思考文本开始逐字流出'},
  {from: at('S5', 0.19), src: 'text-type', volume: 0.26, durationInFrames: 50, comment: 'S5 思考文本流出中段'},
  {from: at('S5', 0.315), src: 'transition-soft', volume: 0.28, durationInFrames: 40, comment: 'S5 收起思考区'},
  {from: at('S5', 0.33), src: 'text-type', volume: 0.34, durationInFrames: 50, comment: 'S5 判断句开始流出'},
  {from: at('S5', 0.44), src: 'data-stream', volume: 0.24, durationInFrames: 50, comment: 'S5 判断句流出中'},
  {from: at('S5', 0.56), src: 'sparkle-touch', volume: 0.36, comment: 'S5 判断句打完,结论落定'},
  {from: at('S5', 0.575), src: 'click-camera', volume: 0.34, comment: 'S5 结论行画出依据线'},
  {from: at('S5', 0.605), src: 'camera-autofocus', volume: 0.36, durationInFrames: 90, comment: 'S5 开始滚向行动卡'},
  {from: at('S5', 0.63), src: 'impact-deep-whoosh', volume: 0.42, durationInFrames: 40, comment: 'S5 行动卡在对话里出现'},
  {from: at('S5', 0.68), src: 'ui-pop', volume: 0.34, comment: 'S5 卡片落定'},
  {from: at('S5', 0.72), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S5 右栏来源条数落位'},
  {from: at('S5', 0.78), src: 'click-camera', volume: 0.33, comment: 'S5 来源分布逐条'},
  {from: at('S5', 0.84), src: 'click-camera', volume: 0.32, comment: 'S5 来源分布逐条 2'},
  {from: at('S5', 0.9), src: 'sparkle-touch', volume: 0.3, comment: 'S5 收束'},
  {from: at('S5', 0.94), src: 'transition-soft', volume: 0.3, durationInFrames: 46, comment: 'S5 交棒行动卡段'},
  {from: at('S5', 0.97), src: 'whoosh-fast', volume: 0.5, durationInFrames: 22, comment: 'S5 段落收尾'},

  // ── S6 行动卡(20s)──
  //   ★ 2026-10-08:三档点亮的时刻随说明幕加长(SEG0_MIN_FRAMES=72 ⇒ seg0R=0.12)重钉,
  //     否则「未排除/高风险」的落位声会比徽章早到;交棒声也对齐到 SEG0_END=0.12。
  {from: at('S6', 0.02), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S6 三档特写切入'},
  {from: at('S6', 0.033), src: 'sparkle-touch', volume: 0.38, comment: 'S6「稳定」点亮'},
  {from: at('S6', 0.058), src: 'sparkle-touch', volume: 0.4, comment: 'S6「未排除」点亮'},
  {from: at('S6', 0.082), src: 'sparkle-touch', volume: 0.44, comment: 'S6「高风险」点亮'},
  {from: at('S6', 0.12), src: 'whoosh-fast', volume: 0.55, durationInFrames: 24, comment: 'S6 交棒设备框'},
  {from: at('S6', 0.3), src: 'impact-deep-whoosh', volume: 0.4, durationInFrames: 34, comment: 'S6 行动卡落定'},
  {from: at('S6', 0.37), src: 'text-type', volume: 0.3, durationInFrames: 50, comment: 'S6 建议逐条'},
  {from: at('S6', 0.44), src: 'camera-autofocus', volume: 0.4, durationInFrames: 90, comment: 'S6 来源标注高亮'},
  {from: at('S6', 0.56), src: 'click-camera', volume: 0.33, comment: 'S6 来源条 2'},
  {from: at('S6', 0.66), src: 'click-camera', volume: 0.33, comment: 'S6 来源条 3'},
  {from: at('S6', 0.76), src: 'click-camera', volume: 0.32, comment: 'S6 来源条 4'},
  {from: at('S6', 0.86), src: 'transition-soft', volume: 0.32, durationInFrames: 46, comment: 'S6 双会话对照落位'},

  // ── S7 记忆与档案(26s)—— ★ 2026-10-07 拆两幕:档案 15s + 记忆 11s ──
  // 幕内比例 → 全段比例的换算:档案幕 r → r*15/26;记忆幕 r → 15/26 + r*11/26。
  // 比例与 S7Memory.tsx 的 a()/b() 同一套,因此画面事件与音效不会脱钩。
  {from: at('S7', 0.005), src: 'whoosh-big', volume: 0.4, durationInFrames: 44, comment: 'S7 档案页浮入'},
  {from: at('S7', 0.05), src: 'sparkle-touch', volume: 0.3, comment: 'S7 档案说明①'},
  {from: at('S7', 0.18), src: 'sparkle-touch', volume: 0.3, comment: 'S7 档案说明②'},
  {from: at('S7', 0.28), src: 'whoosh-fast', volume: 0.42, durationInFrames: 24, comment: 'S7 滚向待确认分组'},
  {from: at('S7', 0.46), src: 'camera-autofocus', volume: 0.42, durationInFrames: 90, comment: 'S7 候选条目描边 draw-on'},
  {from: at('S7', 0.6), src: 'ui-pop', volume: 0.48, comment: 'S7 确认按下(状态翻转)'},
  {from: at('S7', 0.585), src: 'transition-soft', volume: 0.32, durationInFrames: 34, comment: 'S7 切到记忆页'},
  {from: at('S7', 0.661), src: 'sparkle-touch', volume: 0.3, comment: 'S7 记忆第一行落位'},
  {from: at('S7', 0.712), src: 'sparkle-touch', volume: 0.3, comment: 'S7 记忆第二行落位'},
  {from: at('S7', 0.831), src: 'click-camera', volume: 0.34, comment: 'S7 记忆第三行落位'},
  {from: at('S7', 0.873), src: 'click-camera', volume: 0.36, comment: 'S7 高亮「删除」按钮'},
  {from: at('S7', 0.949), src: 'transition-soft', volume: 0.28, durationInFrames: 30, comment: 'S7 收束交棒'},

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
