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
import {SFX_CUE_LEAD} from './sfxLead.generated';

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

/**
 * 带**起音补偿**的 cue 时刻。
 *
 * ★ 为什么需要(2026-10-08):`at()` 给的是「动画事件发生在第几帧」,但素材从被触发
 *   到**变得可听**还有一段落差 —— 实测 16 个素材里 13 个是渐强扫过,能量到自身峰值
 *   10% 还需 1–22 帧(`sparkle` 22 帧、`whoosh-fast` 14 帧)。直接让两者同帧触发,
 *   听感就是「声音比动作晚」。所以把 cue **提前**该素材的落差帧数。
 *
 * 两条硬约束(否则修同步会换来新的错):
 *   ① 结果必须仍落在**本镜头区间内** —— 否则声音漏进上一段(check-sfx 会报「越段」,
 *      而观众听到的是「上一段的尾巴突然响了一声」);
 *   ② 不早于镜头起点(同上,夹紧而不是任其溢出)。
 *
 * 兜底:`SFX_CUE_LEAD` 里没有该素材时按 0 处理(未实测的素材不猜测补偿量)。
 */
function atSfx(shotId: string, ratio: number, src: string): number {
  const s: Shot = shot(shotId);
  const raw = at(shotId, ratio) - (SFX_CUE_LEAD[src] ?? 0);
  return Math.max(s.from, Math.min(s.from + s.duration - 1, raw));
}

export const SFX: SfxEntry[] = [
  // ── S1 品牌开场(4s)──
  {from: atSfx('S1', 0.11, 'transition-soft'), src: 'transition-soft', volume: 0.4, durationInFrames: 42, comment: 'S1 字标压印落定'},
  {from: atSfx('S1', 0.8, 'whoosh-fast'), src: 'whoosh-fast', volume: 0.7, durationInFrames: 20, comment: 'S1 消散交棒'},

  // ── S2 痛点情境(6s)──
  {from: atSfx('S2', 0.05, 'transition-soft'), src: 'transition-soft', volume: 0.28, durationInFrames: 40, comment: 'S2 情境首行'},
  {from: atSfx('S2', 0.62, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.26, comment: 'S2 转折线展开'},
  // ★ 末行「是没人商量」落在 0.72(不是 0.62 —— 0.62 是转折线)。
  //   这条曾按旧时间轴的绝对帧偏移 +88 落在转折线上,与画面事件脱钩。
  {from: atSfx('S2', 0.73, 'impact-deep-whoosh'), src: 'impact-deep-whoosh', volume: 0.34, durationInFrames: 30, comment: 'S2「是没人商量」强调'},

  // ── S3 定位与首页(8s)──
  {from: atSfx('S3', 0.02, 'whoosh-big'), src: 'whoosh-big', volume: 0.45, durationInFrames: 50, comment: 'S3 设备框浮入'},
  {from: atSfx('S3', 0.22, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.32, comment: 'S3 卖点1 点亮'},
  {from: atSfx('S3', 0.33, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.32, comment: 'S3 卖点2 点亮'},
  {from: atSfx('S3', 0.44, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.34, comment: 'S3 卖点3 点亮'},
  {from: atSfx('S3', 0.7, 'transition-soft'), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S3 定位主句'},

  // ── S4 应急入口与八项采集(32s)──
  // 比例与 S4Intake.tsx 的四段划分一致:入口 0-0.13 / 第1题 0.13-0.36 / 快掠 0.36-0.62 / 自由文本 0.62-1
  {from: atSfx('S4', 0.045, 'camera-autofocus'), src: 'camera-autofocus', volume: 0.45, durationInFrames: 90, comment: 'S4 高亮圈锁定应急入口'},
  {from: atSfx('S4', 0.13, 'transition-soft'), src: 'transition-soft', volume: 0.32, durationInFrames: 34, comment: 'S4 进入第 1 题'},
  {from: atSfx('S4', 0.16, 'click-camera'), src: 'click-camera', volume: 0.42, comment: 'S4 勾选「明显疼痛」'},
  // 快掠:四道题各一次切题音(比例均分 0.36→0.62)
  {from: atSfx('S4', 0.38, 'click-camera'), src: 'click-camera', volume: 0.4, comment: 'S4 快掠 第3题'},
  {from: atSfx('S4', 0.44, 'click-camera'), src: 'click-camera', volume: 0.38, comment: 'S4 快掠 第4题'},
  {from: atSfx('S4', 0.5, 'click-camera'), src: 'click-camera', volume: 0.36, comment: 'S4 快掠 第5题'},
  {from: atSfx('S4', 0.56, 'click-camera'), src: 'click-camera', volume: 0.34, comment: 'S4 快掠 第6题'},
  // 自由文本段:打字声 + 提交
  {from: atSfx('S4', 0.66, 'text-type'), src: 'text-type', volume: 0.36, durationInFrames: 60, comment: 'S4 写下现场的样子'},
  {from: atSfx('S4', 0.93, 'ui-pop'), src: 'ui-pop', volume: 0.5, comment: 'S4 按下「提交，开始分析」'},

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
  {from: atSfx('S5', 0.004, 'transition-soft'), src: 'transition-soft', volume: 0.32, durationInFrames: 40, comment: 'S5 分析段切入'},
  {from: atSfx('S5', 0.02, 'data-stream'), src: 'data-stream', volume: 0.28, durationInFrames: 60, comment: 'S5「正在分析…」底噪'},
  {from: atSfx('S5', 0.05, 'ui-pop'), src: 'ui-pop', volume: 0.34, comment: 'S5 展开思考区(使用者的一次动作)'},
  {from: atSfx('S5', 0.075, 'text-type'), src: 'text-type', volume: 0.32, durationInFrames: 50, comment: 'S5 思考文本开始逐字流出'},
  {from: atSfx('S5', 0.19, 'text-type'), src: 'text-type', volume: 0.26, durationInFrames: 50, comment: 'S5 思考文本流出中段'},
  {from: atSfx('S5', 0.315, 'transition-soft'), src: 'transition-soft', volume: 0.28, durationInFrames: 40, comment: 'S5 收起思考区'},
  {from: atSfx('S5', 0.33, 'text-type'), src: 'text-type', volume: 0.34, durationInFrames: 50, comment: 'S5 判断句开始流出'},
  {from: atSfx('S5', 0.44, 'data-stream'), src: 'data-stream', volume: 0.24, durationInFrames: 50, comment: 'S5 判断句流出中'},
  {from: atSfx('S5', 0.56, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.36, comment: 'S5 判断句打完,结论落定'},
  {from: atSfx('S5', 0.575, 'click-camera'), src: 'click-camera', volume: 0.34, comment: 'S5 结论行画出依据线'},
  {from: atSfx('S5', 0.605, 'camera-autofocus'), src: 'camera-autofocus', volume: 0.36, durationInFrames: 90, comment: 'S5 开始滚向行动卡'},
  {from: atSfx('S5', 0.63, 'impact-deep-whoosh'), src: 'impact-deep-whoosh', volume: 0.42, durationInFrames: 40, comment: 'S5 行动卡在对话里出现'},
  {from: atSfx('S5', 0.68, 'ui-pop'), src: 'ui-pop', volume: 0.34, comment: 'S5 卡片落定'},
  {from: atSfx('S5', 0.72, 'transition-soft'), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S5 右栏来源条数落位'},
  {from: atSfx('S5', 0.78, 'click-camera'), src: 'click-camera', volume: 0.33, comment: 'S5 来源分布逐条'},
  {from: atSfx('S5', 0.84, 'click-camera'), src: 'click-camera', volume: 0.32, comment: 'S5 来源分布逐条 2'},
  {from: atSfx('S5', 0.9, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.3, comment: 'S5 收束'},
  {from: atSfx('S5', 0.94, 'transition-soft'), src: 'transition-soft', volume: 0.3, durationInFrames: 46, comment: 'S5 交棒行动卡段'},
  {from: atSfx('S5', 0.97, 'whoosh-fast'), src: 'whoosh-fast', volume: 0.5, durationInFrames: 22, comment: 'S5 段落收尾'},

  // ── S6 行动卡(20s)──
  //   ★ 2026-10-08:三档点亮的时刻随说明幕加长(SEG0_MIN_FRAMES=72 ⇒ seg0R=0.12)重钉,
  //     否则「未排除/高风险」的落位声会比徽章早到;交棒声也对齐到 SEG0_END=0.12。
  {from: atSfx('S6', 0.02, 'transition-soft'), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S6 三档特写切入'},
  {from: atSfx('S6', 0.033, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.38, comment: 'S6「稳定」点亮'},
  {from: atSfx('S6', 0.058, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.4, comment: 'S6「未排除」点亮'},
  {from: atSfx('S6', 0.082, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.44, comment: 'S6「高风险」点亮'},
  {from: atSfx('S6', 0.12, 'whoosh-fast'), src: 'whoosh-fast', volume: 0.55, durationInFrames: 24, comment: 'S6 交棒设备框'},
  {from: atSfx('S6', 0.3, 'impact-deep-whoosh'), src: 'impact-deep-whoosh', volume: 0.4, durationInFrames: 34, comment: 'S6 行动卡落定'},
  {from: atSfx('S6', 0.37, 'text-type'), src: 'text-type', volume: 0.3, durationInFrames: 50, comment: 'S6 建议逐条'},
  {from: atSfx('S6', 0.44, 'camera-autofocus'), src: 'camera-autofocus', volume: 0.4, durationInFrames: 90, comment: 'S6 来源标注高亮'},
  {from: atSfx('S6', 0.56, 'click-camera'), src: 'click-camera', volume: 0.33, comment: 'S6 来源条 2'},
  {from: atSfx('S6', 0.66, 'click-camera'), src: 'click-camera', volume: 0.33, comment: 'S6 来源条 3'},
  {from: atSfx('S6', 0.76, 'click-camera'), src: 'click-camera', volume: 0.32, comment: 'S6 来源条 4'},
  {from: atSfx('S6', 0.86, 'transition-soft'), src: 'transition-soft', volume: 0.32, durationInFrames: 46, comment: 'S6 双会话对照落位'},

  // ── S7 记忆与档案(26s)—— ★ 2026-10-07 拆两幕:档案 15s + 记忆 11s ──
  // 幕内比例 → 全段比例的换算:档案幕 r → r*15/26;记忆幕 r → 15/26 + r*11/26。
  // 比例与 S7Memory.tsx 的 a()/b() 同一套,因此画面事件与音效不会脱钩。
  {from: atSfx('S7', 0.005, 'whoosh-big'), src: 'whoosh-big', volume: 0.4, durationInFrames: 44, comment: 'S7 档案页浮入'},
  {from: atSfx('S7', 0.05, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.3, comment: 'S7 档案说明①'},
  {from: atSfx('S7', 0.18, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.3, comment: 'S7 档案说明②'},
  {from: atSfx('S7', 0.28, 'whoosh-fast'), src: 'whoosh-fast', volume: 0.42, durationInFrames: 24, comment: 'S7 滚向待确认分组'},
  {from: atSfx('S7', 0.46, 'camera-autofocus'), src: 'camera-autofocus', volume: 0.42, durationInFrames: 90, comment: 'S7 候选条目描边 draw-on'},
  {from: atSfx('S7', 0.6, 'ui-pop'), src: 'ui-pop', volume: 0.48, comment: 'S7 确认按下(状态翻转)'},
  {from: atSfx('S7', 0.585, 'transition-soft'), src: 'transition-soft', volume: 0.32, durationInFrames: 34, comment: 'S7 切到记忆页'},
  {from: atSfx('S7', 0.661, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.3, comment: 'S7 记忆第一行落位'},
  {from: atSfx('S7', 0.712, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.3, comment: 'S7 记忆第二行落位'},
  {from: atSfx('S7', 0.831, 'click-camera'), src: 'click-camera', volume: 0.34, comment: 'S7 记忆第三行落位'},
  {from: atSfx('S7', 0.873, 'click-camera'), src: 'click-camera', volume: 0.36, comment: 'S7 高亮「删除」按钮'},
  {from: atSfx('S7', 0.949, 'transition-soft'), src: 'transition-soft', volume: 0.28, durationInFrames: 30, comment: 'S7 收束交棒'},

  // ── S8 案例库(13s)──
  {from: atSfx('S8', 0.02, 'transition-soft'), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S8 案例库切入'},
  {from: atSfx('S8', 0.45, 'whoosh-fast'), src: 'whoosh-fast', volume: 0.4, durationInFrames: 24, comment: 'S8 滚向虚构样例'},
  {from: atSfx('S8', 0.8, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.42, comment: 'S8 虚构样例标签点亮'},

  // ── S9 边界与收尾(10s)──
  {from: atSfx('S9', 0.02, 'transition-soft'), src: 'transition-soft', volume: 0.3, durationInFrames: 40, comment: 'S9 边界声明第一句'},
  {from: atSfx('S9', 0.1, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.26, comment: 'S9 第二句'},
  {from: atSfx('S9', 0.19, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.26, comment: 'S9 第三句'},
  {from: atSfx('S9', 0.43, 'riser-cine'), src: 'riser-cine', volume: 0.38, durationInFrames: 90, comment: 'S9 riser 品牌组装段起'},
  {from: atSfx('S9', 0.63, 'impact-deep-whoosh'), src: 'impact-deep-whoosh', volume: 0.45, durationInFrames: 60, comment: 'S9 字标 stamp 落地(全片峰值)'},
  {from: atSfx('S9', 0.73, 'sparkle'), src: 'sparkle', volume: 0.3, durationInFrames: 40, comment: 'S9 rule 长出余韵'},
  {from: atSfx('S9', 0.76, 'sparkle-touch'), src: 'sparkle-touch', volume: 0.26, comment: 'S9 光扫掠过'},
  // 渐隐收束:放在段尾但**留出样本自身时长**,否则会越过全片末尾(曾被 check-sfx 抓出)
  {from: atSfx('S9', 0.85, 'transition-soft'), src: 'transition-soft', volume: 0.28, durationInFrames: 40, comment: 'S9 渐隐收束'},
];
