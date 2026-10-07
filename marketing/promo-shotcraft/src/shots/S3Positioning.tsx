// S3 产品定位与首页 —— 用**真实 HomePage 组件**当主体。
//
// 与旧版(截图版)的差别:首页不再是一张 PNG + 手写叠加层,而是真的 HomePage 在渲染。
// 因此应急入口的呼吸点、按钮圆角、页头字距全部与真实产品一致,
// 高亮直接作用在元素上(不会再出现「框错位置」)。
//
// ★ v16:时间点改为**从本段时长按比例派生**(见 lib/shotTiming.ts)。
//   原先写死帧号(浮入 [0,26]、眉标 [16,40]、卖点 [40+i*16, 62+i*16]、主句 [110,138]、
//   正文 [140,166]、淡出 [166,180]、相机推到 1.2 铺满 180f)。
//   段长从 180f 改到 240f 后全部失配:末句落定后到段尾会多出 74 帧(2.5s)无事发生。
//   现在相机时长直接读 t.duration,推近速率自动保持 —— 8s 段里每 30 帧仍 +0.025,
//   高于 lib/camera.ts 给的「每 30 帧至少 0.02」下限。
//
// 段长 240f / 8s,四个节拍(比例):
//   ① 0.00-0.11   首页浮入(透明度 + 40px 上移,大面积变化)
//   ② 0.07-0.53   眉标落位 → 三个卖点逐条落位(每条占 0.12,含落位动作本身)
//   ③ 0.29-0.54   ★ 首页内部两条真实入口被逐个强调(应急 → 日常),说明区同步换词
//   ④ 0.61-0.92   定位主句落位 → 两条入口的收束句落位 → 0.92 起淡出
//   贯穿:相机 1.00→1.20 **单向推近**(无周期漂移 —— 2026-10-07 按用户裁决删除,
//         见 lib/camera.ts 顶部说明);两条入口的强调各是**一次离散事件**。
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {MemoryRouter} from 'react-router';

import {HomePage} from '../../../../apps/web/src/app/pages/HomePage';
import {DeviceStage, FilmRoot} from '../lib/DeviceStage';
import {NoteBody, NoteKicker, NoteTitle, NOTE_X} from '../lib/Shot';
import {useShotTiming} from '../lib/shotTiming';

/** 三个卖点(文案取自产品设计契约,不编造)。 */
const FEATURES = [
  {t: '记得住', d: '孩子的档案与你们的经验,自动沉淀'},
  {t: '查得到', d: '每条建议都能点开看出处与适用范围'},
  {t: '改得动', d: '系统的推断只以「待确认」存在,你说了算'},
] as const;

/**
 * ★ 首页真实元素的强调:**不画叠加框,改真实元素自己**。
 *
 * 为什么不用 S4 那种「按实测坐标画一个圈」的做法:
 *   坐标圈在相机缩放后会漂 —— 圆心按 transformOrigin(center center) 缩放,
 *   而圈本身是画布坐标里的固定位置,两者只在 scale=1 时重合。S4 的圈落在
 *   小幅推近(≈1.02)的窗口里所以看不出来;本段要推到 1.20,照抄必然框偏。
 *   而这里作用在**真实元素**上,元素的 outline / drop-shadow 由浏览器
 *   随元素一起变换 —— 缩放、位移、屏内滚动全部自动跟随,不可能框错位置
 *   (同一思路见 lib/DeviceStage.tsx 顶部对「截图路线缺陷③」的说明)。
 *
 * 选择器取自产品契约类名(shared/styles/components.css 的 .emergency-entry /
 * .daily-entry),HomePage 正是用这两个类名渲染那两张卡。影片里不复制它们的
 * 几何,只叠一层强调。作用域限定在 .film-root 内,不影响产品自身样式。
 *
 * @param sel 契约类名
 * @param turnOn 强调淡入(0..1)
 * @param pop 落位瞬间的**一次性**回弹(0..1)。它是离散事件:强调亮起时描边先张开
 *            再收到稳态,之后**保持静止**。不再用 sin 做持续呼吸 —— 那种无语义的
 *            连续运动已被用户否决(见 lib/camera.ts 顶部)。
 */
function emphasisCss(sel: string, turnOn: number, pop: number): string {
  // 描边透明度跟随 turnOn:0 时 outline 全透明(等于没有),不做 display 切换,
  // 避免布局抖动。
  const strokeAlpha = Math.round((1 - turnOn) * 100);
  // 稳态 4px/18px;落位瞬间张开到 10px/36px 再收回 —— 一帧就能看出边界在动,
  // 且**动完就停**。
  const offset = 4 + pop * 6;
  const glow = 18 + pop * 18;
  const glowAlpha = Math.round((1 - turnOn * (0.4 + pop * 0.35)) * 100);
  return `
    .film-root ${sel} {
      outline: 3px solid color-mix(in srgb, var(--accent), transparent ${String(strokeAlpha)}%);
      outline-offset: ${offset.toFixed(2)}px;
      filter: drop-shadow(0 0 ${glow.toFixed(2)}px color-mix(in srgb, var(--accent), transparent ${String(glowAlpha)}%));
    }
  `;
}

export const S3Positioning: React.FC = () => {
  const frame = useCurrentFrame();
  const t = useShotTiming();

  /**
   * 首页浮入:从 0.35 起(不是 0)—— 保证 **f0 就有内容**。
   *
   * ★ v16 二次修正:初版 `[0, 1]` 也就是 f0 时 opacity=0 —— 而 S2 在末尾把画面
   *   压暗后回升到亮纸、内容已淡净,于是 f300(= S3 第一帧)**整屏只有一个颜色**
   *   (我全片扫均匀帧时抓出 std=0.000)。
   *   改为起手 0.35:首页一上来就隐约在场(播 0.11 段长的 65% 完成浮入),
   *   f0 因此有可见内容;浮入动作本身仍在,只是起点前移。
   */
  const frameIn = interpolate(frame, t.span(0, 0.11), [0.35, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.2, 0.7, 0.25, 1),
  });
  const enterY = (1 - frameIn) * 40;

  // 相机:★ 2026-10-08 删除「全程线性推近」(用户原话:「我为什么还能看到手机框在动?
  //   太不好看了」)。原来是 `pushCamera(frame, 1.0, 1.2, t.duration)` —— 曲线铺满整段,
  //   而 scale 加在「外壳 + 屏幕」整层上 ⇒ **黑色边框与机身跟着一起放大**,8s 不停。
  //   本段没有需要「凑近看」的新对象(三个卖点是原地落位),因此运镜整体去掉:
  //   设备框恒定 1.0,画面只靠卖点落位与页内内容动。
  //   (旧注释里「推到 1.20 是为了帧差可见」的说法正是被否决的那类理由 —— 为度量而造运动。)
  const scale = 1.0;

  // 三个卖点:每条占 0.12 段长(8s 段里约 29f),间隔 0.09 → 落位动作之间有 0.03 的呼吸。
  // 为什么把起点放在 0.22:0.22 之前是「首页浮入 + 眉标」两拍,卖点从第 3 拍开始,
  // 顺序与观众视线一致(先看到设备,再读卖点)。
  const capIn = (i: number) =>
    interpolate(frame, t.span(0.22 + i * 0.09, 0.34 + i * 0.09), [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.2, 0.7, 0.25, 1),
    });

  const kickerIn = interpolate(frame, t.span(0.067, 0.167), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const titleIn = interpolate(frame, t.span(0.61, 0.77), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.2, 0.7, 0.25, 1),
  });
  const fadeOut = interpolate(frame, t.span(0.92, 1), [1, 0.06], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // ── ③ 首页内部两条真实入口的强调 ──
  // 应急入口先亮(0.29-0.375),日常入口后亮(0.45-0.535)——与它们在同一屏内的
  // 上下顺序一致,也与说明区那句话的读法一致(先说应急,再说日常)。
  const emOn = interpolate(frame, t.span(0.29, 0.375), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.2, 0.75, 0.3, 1),
  });
  const dailyOn = interpolate(frame, t.span(0.45, 0.535), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.2, 0.75, 0.3, 1),
  });
  // 两条入口各一次**离散**落位事件:强调亮起时描边张开再收回,之后保持静止。
  //   ★ 2026-10-07:替换原先的 sin 持续呼吸(20f 周期)—— 那是同一类无语义连续运动。
  const emPop = 1 - interpolate(frame, t.span(0.375, 0.42), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const dailyPop = 1 - interpolate(frame, t.span(0.535, 0.58), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  // 说明区跟随换词:强调应急时讲应急,强调日常时讲日常。
  //
  // ★ 用**两段不重叠**的时间窗,而不是一个 swap 值同时驱动淡入淡出:
  //   两句是 position:absolute 叠在同一位置,若同时可见就会**文字重叠**。
  //   因此让旧句在自己的窗口内收干净(outFade 到 1),新句之后才开始(inFade 从 0)。
  const outFade = interpolate(frame, t.span(0.46, 0.5), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const inFade = interpolate(frame, t.span(0.51, 0.55), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  const captionStyle: React.CSSProperties = {
    fontFamily: 'var(--font-body)', fontSize: 20, color: 'var(--accent)', letterSpacing: '0.02em',
  };

  return (
    <FilmRoot>
      {/* 强调样式:按帧生成,值全部是 frame 的纯函数(无墙钟、无随机) */}
      <style>{emphasisCss('.emergency-entry', emOn, emPop)}</style>
      <style>{emphasisCss('.daily-entry', dailyOn, dailyPop)}</style>

      <div style={{position: 'absolute', inset: 0, opacity: fadeOut}}>
        <DeviceStage cx={640} cy={540} scale={scale} ty={enterY} opacity={frameIn}>
          <MemoryRouter initialEntries={['/']}>
            <HomePage />
          </MemoryRouter>
        </DeviceStage>

        <div style={{position: 'absolute', left: NOTE_X, top: 250, width: 790}}>
          <NoteKicker opacity={kickerIn}>篝火智答 · 一个装在口袋里的照护伙伴</NoteKicker>
          <NoteTitle opacity={titleIn} size={42}>
            现场遇到正在发生的情况,
            <br />
            回答几个问题,拿到可行动的建议。
          </NoteTitle>

          <div style={{marginTop: 46, display: 'flex', flexDirection: 'column', gap: 26}}>
            {FEATURES.map((f, i) => {
              const on = capIn(i);
              return (
                <div
                  key={f.t}
                  style={{
                    display: 'flex', alignItems: 'baseline', gap: 20,
                    opacity: on, transform: `translateY(${(1 - on) * 14}px)`,
                  }}
                >
                  <span
                    style={{
                      fontFamily: 'var(--font-display)', fontSize: 32, fontWeight: 500,
                      color: 'var(--fg)', flexShrink: 0, width: 130,
                    }}
                  >
                    {f.t}
                  </span>
                  <span style={{fontFamily: 'var(--font-body)', fontSize: 21, color: 'var(--muted)'}}>
                    {f.d}
                  </span>
                </div>
              );
            })}
          </div>

          {/* 强调对象的点名:与首页里被点亮的那张卡一一对应。
              ★ v16 修正:初版两句用**同时交叉淡入**(out = emOn*(1-swap), in = dailyOn*swap)。
                在 swap≈0.5 的过渡帧里两句都半透明可见 —— 而它们 position:absolute 叠在
                同一位置,于是画面上出现**两行文字重叠**(实测 f190 可见)。
                改成**先出后进**:out 在 swap 前段就把自己收干净,in 在 swap 后段才开始,
                两者在时间上不重叠。整句替换仍然清晰(比渐变更容易被看见)。 */}
          <div style={{position: 'relative', marginTop: 30, height: 30}}>
            <div style={{...captionStyle, position: 'absolute', top: 0, opacity: emOn * (1 - outFade)}}>
              ① 现在需要帮助 —— 首页唯一的强调单元
            </div>
            <div style={{...captionStyle, position: 'absolute', top: 0, opacity: dailyOn * inFade}}>
              ② 日常咨询 —— 想聊聊正在准备或刚发生的事
            </div>
          </div>

          <NoteBody
            opacity={interpolate(frame, t.span(0.78, 0.92), [0, 1], {
              extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
            })}
            top={36}
          >
            两条入口:现在需要帮助走应急,想聊聊正在准备的事走日常。
          </NoteBody>
        </div>
      </div>
    </FilmRoot>
  );
};
