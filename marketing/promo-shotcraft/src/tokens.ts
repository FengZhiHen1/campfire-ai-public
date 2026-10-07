// 视觉 tokens:从 docs/design/tokens.css 提取,不另造值。
export const C = {
  bg: '#fbf6ee',
  surface: '#fffdf8',
  surfaceWarm: '#f1e3cf',
  fg: '#201914',
  fg2: '#4c4037',
  muted: '#7a6d63',
  border: '#ded2c3',
  borderSoft: '#eee4d7',
  accent: '#c2410c',
  accentOn: '#fffdf8',
  statusStable: '#3f7a44',
  statusUnruled: '#b45309',
  statusHigh: '#b3372f',
} as const;

export const FONT_DISPLAY =
  '"Noto Serif SC", "Songti SC", "STSong", "SimSun", Georgia, serif';
export const FONT_BODY =
  'system-ui, -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';
export const FONT_MONO =
  '"SF Mono", ui-monospace, Menlo, Consolas, monospace';

// 动效性格 tokens:平静关怀预设微调(见 DESIGN_SPEC 阶段 1)
export const MOTION = {
  enterFrames: 32,
  transitionFrames: 24,
  brandHoldFrames: 45,
  contentHoldFrames: 30,
  easeInOut: 'bezier(0.4, 0, 0.2, 1)',
  easeOut: 'bezier(0, 0, 0.2, 1)',
  overshoot: 1.02,
  squash: 0.04,
} as const;

// 画布
export const CANVAS = { w: 1920, h: 1080 } as const;
// 手机逻辑视口(采集素材的坐标系)
export const PHONE = { w: 390, h: 844 } as const;
// PhoneStage 用的裸常量(DESIGN.md 规格:390×844 屏 + 12px bezel)
export const PHONE_W = 390;
export const PHONE_H = 844;
