// 视频工程的设计 token 镜像,唯一权威是 docs/design/tokens.css。
// 改色改字先改契约文件再同步此处,不在本文件发明新值。

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

// 画布与构图 A 布局常量(1920×1080)
export const CANVAS = {width: 1920, height: 1080} as const;
export const PHONE = {
  w: 420,
  h: 912,
  cx: 360, // 手机中心 x
  cy: 540, // 手机中心 y
} as const;
