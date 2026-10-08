// DeviceStage —— 用**真实产品组件**当画面主体,由帧驱动相机与滚动。
//
// ── 为什么换掉截图路线(旧 PhoneStage) ──────────────────────────────────
// 旧路线 = <Img src="textures/states/home.png"> + 手写绝对定位叠加层,四个结构性缺陷:
//   ① 叠加层坐标靠猜 → 勾选标记对不齐真实复选框;
//   ② 截图定高 → 滚动量一大就滑出画面露空白;
//   ③ 高亮只能另画一层 → 「框没匡准」;
//   ④ 流式只能伪造(本质是滚动截图),不是逐 token。
// 组件路线把这四条一起消掉。
//
// ── 关键设计决定:不重写产品几何 ───────────────────────────────────────
// 产品外壳几何(390×844 / bezel 12 / 圆角 56 / 暖色 bezel)由
// apps/web/src/shared/styles/global.css 的 `.device` 段在 `@media (min-width:560px)`
// 下声明。**不要在这里重新声明一遍** —— 那会与产品契约产生第二真源,并已实测把样式
// 压坏过一次(display:contents 到处生效、CSS Modules 类名失效)。
//
// 正确做法:让渲染视口真的 ≥560px,让产品的媒体查询自然命中。这是唯一能保证
// 「画面 = 真实产品长什么样」的方法,且不需要任何几何覆盖。
//
// ★ 全局样式层必须在这里显式 import:产品在浏览器里由 main.tsx 引入
//   tokens/global/components 三层,影片没有 main.tsx —— 漏引入会让所有契约类名
//   (.panel/.tile/.device/…) 全部退化为浏览器默认外观(实测踩过)。
import '../../../../apps/web/src/shared/styles/tokens.css';
import '../../../../apps/web/src/shared/styles/global.css';
import '../../../../apps/web/src/shared/styles/components.css';
// consultComponents.css 是咨询面各页的契约类名表(.selection/.check-box/.bubble-user/
// .msg-doc/.action-card/.reasoning-row…)。产品里由消费它的页面各自 import,
// 影片也必须引入 —— 漏掉它,选择卡会退化成「一行挤满的裸 checkbox」(实测踩过)。
import '../../../../apps/web/src/features/consult/view/consultComponents.css';

import {useLayoutEffect, useRef} from 'react';
import {AbsoluteFill} from 'remotion';

/** 影片渲染视口宽度。必须 ≥560px,否则产品的外壳媒体查询不命中(见上方说明)。 */
export const FILM_VIEWPORT_WIDTH = 1920;

/**
 * 影片级样式:只做两件事,都**不涉及几何**。
 *
 * ① 滚动:★ 用 **transform**(`--film-scroll` 变量 + `.device-screen > *` 位移),
 *    **不是**原生 `scrollTop`。
 *
 *    ── 为什么不许用原生滚动(实测否决,不是偏好)────────────────────
 *    看起来更自然:产品自己的 `.device-screen` 就是 `overflow-y:auto` 的滚动容器,
 *    在 layout effect 里写 `scrollTop` 不就能"用真机的滚动"吗?
 *    **实测不行。** 诊断探针证实 commit 阶段 `scrollTop=300` 确实写进去了
 *    (`screen.scrollH=1144 clientH=844 top=300 ovY=auto disp=block`),
 *    但 Remotion 的截图流程会**重置滚动位置** —— A/B 对照:同一个组件、同一帧、
 *    只让 scrollY 不同,渲染出的 PNG **SHA256 完全相同**
 *    (`8C01CD888F833DBD…`),即画面纹丝不动。
 *    换成 transform 后同一 A/B 得到不同的 SHA256 ⇒ 只有 transform 能被截进画面。
 *
 *    ── 那为什么不用 `> .phone-shell` 那条更"干净"的选择器 ────────────
 *    v14 初版写的是 `.device-screen > .phone-shell { transform: … }`,它有两个
 *    结构性缺陷:
 *      · `.phone-shell` **不是所有页面都有**。只有走 AppShell 的页面
 *        (ProfilePage / LibraryPage)才有这个节点;ChatScreen 与 ActionCardScreen
 *        直接挂 DeviceFrame,**选择器命中 0 个元素** —— S5/S6 的滚动因此完全失效
 *        (实测:脚本要求移动 731px,画面只动 38px,且改三次曲线都纹丝不动)。
 *        现在用 `.device-screen > *`(见下方 · 通用子元素)。
 *      · 产品页头是 `position: sticky`(components.css)。sticky 的参照系原本是
 *        滚动容器;改用 transform 后容器不再滚动,页头会被一起推走、**不再吸顶**。
 *        因此页头与 tab-bar 需要**反向补偿**(见下方 ①b),并在页头上缘贴一层
 *        同色遮罩盖住接缝(见 ①c) —— 没有这两条就会看到「页头往上跑」与
 *        「页头上方露出上一屏内容」。
 *
 *    确定性说明:transform 由 `useLayoutEffect` 在绘制前同步写入
 *    (scroll 量按真实 `scrollHeight - clientHeight` 夹紧),
 *    因此同一帧两次渲染得到同一位置(已用同帧双渲染哈希验证)。
 *
 * ② 关闭墙钟动画:产品 CSS 含 `animation: ...240ms` 之类按真实时间播放的进入动效,
 *    在 Remotion 里会导致同一帧两次渲染结果不同(违反确定性渲染硬约束)。
 *    影片的运动全部来自 useCurrentFrame()。
 */
export const FilmShellStyles: React.FC = () => (
  <style>{`
    /* ⓪ 舞台归位:产品的 .device-stage 在 ≥560px 下是居中 grid
     *   (place-items:center; min-height:100svh; padding:24px)。
     *   影片里设备位置由相机(cx/cy)决定,舞台不该再自己居中 ——
     *   而且 100svh 在 Remotion 下解析为画布高(1080),比我们的摆放盒(868)高,
     *   会让设备在盒内溢出、垂直偏移约 +106px(实测)。
     *   这里只中和舞台的布局,**不碰 .device 的任何几何**(尺寸/圆角/bezel 仍来自产品契约)。 */
    .film-root .device-stage {
      display: block !important;
      min-height: 0 !important;
      padding: 0 !important;
    }

    /* ① 屏内滚动:transform 影片自己的包装层。
     *
     * 选择器用 .device-screen 的直接子元素(*),因为**每个页面都有**这个节点:
     *   · AppShell 页(档案/案例库) → .phone-shell
     *   · ChatScreen                → .film-chat
     *   · ActionCardScreen          → .film-chat-thread
     * 初版写的是 .device-screen > .phone-shell —— 只有 AppShell 页才命中,
     * S5/S6 完全没滚动(独立审查实测:要求移动 731px,画面只动 38px)。
     *
     * 为什么必须 transform 而不能用原生 scrollTop:
     *   实测 scrollTop 写进去了、截图却仍是未滚动状态,Remotion 的截图流程会重置它。
     *   证据:A/B 对照(同组件、同帧、只改 scrollY)输出 SHA256 完全相同。
     *
     * 为什么不用 overflow:hidden:保留 auto 提供裁剪框(裁掉移出屏幕区的内容),
     *   且不改变布局。本构造下 scrollTop 恒为 0,不会出现双重滚动。 */
    .film-root .device-screen > *:not(.film-chat) {
      transform: translateY(calc(-1 * var(--film-scroll, 0px)));
      will-change: transform;
    }

    /* ★★ 2026-10-07:对话页(ChatScreen)的滚动改挂在 **thread 的子元素** 上。
     *
     * 为什么:.film-chat 是 height:100% 的外壳,溢出发生在它内部的 .film-chat-thread
     *   (那个节点自己 overflow-y:auto,且在 .film-chat 里是 flex:1、有确定高度)。
     *   于是:
     *     · 夹紧算的是 .device-screen 的 scrollHeight−clientHeight ⇒ 恒为 0;
     *     · 位移又把整个 .film-chat(含页头与输入区)一起推走。
     *   实测后果:S5 让行动卡在对话里出现后,卡片只露顶部约 170px、被输入区裁断,
     *   且无论给多大的 scrollY 都不动(用户气泡始终停在原位)。
     *   ⇒ 现在夹紧改用 .film-chat-thread(见 useFilmScroll),位移落在它的子元素上,
     *     页头与输入区因此自然保持不动,**不再需要反向补偿**(故下面的补偿用
     *     :has(.film-chat) 把对话页排除掉)。
     *   范围:只有 S5 用 ChatScreen,故不影响 S6(S6 的 .film-chat-thread 高度是 auto,
     *     夹紧会恒为 0 —— 所以那里必须继续走 .device-screen,不能一概而论)。 */
    .film-root .film-chat .film-chat-thread > * {
      transform: translateY(calc(-1 * var(--film-scroll, 0px)));
      will-change: transform;
    }

    /* ①b 反向补偿「本该常驻」的元素。
     *
     * 为什么需要:产品的吸顶页头是 .subpage-head(position:sticky)、底部导航是
     * .tab-bar(position:fixed,包含块靠 .device 的 translateZ 建立)。把滚动换成
     * 父层 transform 后:
     *   · sticky 的参照系(滚动容器)不再滚动 → 页头随内容被推走、不吸顶;
     *   · 被 transform 的祖先会成为 fixed 后代的**新包含块** → 页脚也随内容走。
     * 两者都是「产品本该常驻的 UI 跑掉了」,属保真度缺陷(独立审查在 S8/S7 抽帧确认)。
     *
     * 修法:给它们加上与滚动量**等量反向**的位移,净位移归零 → 视觉上常驻原位。
     * --film-scroll 定义在外层盒上,CSS 变量会继承,因此这里读得到。
     * 只补偿这两类元素;正文继续跟着滚动。
     *
     * ★ 对话页例外:那里位移不在 .device-screen 层(见上方说明),页头本来就不动;
     *   若仍补偿,反而会把页头按 --film-scroll 推下去。用 :has() 排除。 */
    .film-root .device-screen:not(:has(.film-chat)) .subpage-head,
    .film-root .device-screen:not(:has(.film-chat)) .tab-bar {
      transform: translateY(var(--film-scroll, 0px));
    }
    .film-root .device-screen .subpage-head { z-index: 20; }
    .film-root .device-screen .tab-bar { z-index: 30; }

    /* ①c 遮住页头**上方**那条缝。
     *
     * 为什么需要:页头在文档流里位于内容之后(自然偏移 = shell 的 padding 等),
     * 反向补偿把「滚上去的内容」留在了它上方 —— 实测 S8 在页头上方露出一条约 80px
     * 的上一条案例尾部文字。真机上这条缝不存在:页头是 sticky,它上方就是滚动容器的
     * 裁剪边界,内容滚过去被页头自己的不透明底色盖住。
     *
     * 修法:用页头的伪元素向上铺一块同色背景(足够高),等价于把裁剪边界提到屏幕顶。
     * 只铺背景色,不占布局、不遮正文(它在页头之上、z-index 低于页头内容)。 */
    .film-root .device-screen .subpage-head::before {
      content: '';
      position: absolute;
      left: 0;
      right: 0;
      bottom: 100%;
      height: 240px;
      background: var(--surface);
      pointer-events: none;
    }
    .film-root .device-screen::-webkit-scrollbar { display: none; }
    .film-root .device-screen { scrollbar-width: none; }

    /* ② 关闭墙钟动画与过渡(确定性渲染硬约束) */
    .film-root *, .film-root *::before, .film-root *::after {
      animation: none !important;
      transition: none !important;
    }

    /* ③ 影片自建的对话页布局。
     *   为什么需要:产品的布局类 .workspace/.thread/.footer 出自 chatPage.module.css
     *   (CSS Modules → 类名带哈希),影片无法从外部复用带哈希的类名。
     *   这里用等价声明复刻那几条布局规则(仅布局:flex 分配与内滚动,不含任何视觉),
     *   消息/气泡/卡片的**视觉**仍由 consultComponents.css 的契约类名提供。 */
    .film-root .film-chat {
      /* 对话页的外层:占满设备屏、列向排布,让 thread 吃掉中间空间、footer 贴底。
         原先这条只有行内 style,ChatScreen 上的 className 是个**空类名**
         (类名保真检查抓出:产品与影片样式里都查不到它)。行内 style 确实起了作用,
         但留下一个「看起来有样式、其实没有」的类名会误导后来人 ——
         现在把它落成真规则,行内只保留 background(那是页面级视觉,不属于布局)。
         注:本注释不能出现反引号 —— 它所在的 CSS 是模板字符串,反引号会提前闭合。 */
      display: flex;
      flex-direction: column;
      height: 100%;
    }
    .film-root .film-chat-thread {
      display: flex;
      flex: 1 1 auto;
      flex-direction: column;
      gap: var(--space-4);
      min-height: 0;
      padding: var(--space-4) var(--container-gutter-phone) var(--space-4);
      overflow-y: auto;
      overscroll-behavior: contain;
    }
    .film-root .film-chat-footer {
      display: flex;
      flex: none;
      flex-direction: column;
      gap: var(--space-2);
      padding: var(--space-3) var(--container-gutter-phone)
        calc(var(--space-3) + env(safe-area-inset-bottom, 0px));
      border-top: 1px solid var(--border-soft);
      background: var(--surface);
    }
    /* 消息流内的元素不应被 flex 压缩(否则长文本会被挤成一团) */
    .film-root .film-chat-thread > * { flex: none; }
  `}</style>
);

/**
 * 把 `scrollY` 变成屏内内容的位移(transform),并**按真实内容高度夹紧**。
 *
 * ── 为什么不用原生 `scrollTop`(实测否决) ────────────────────────────────
 * 诊断探针实测:commit 阶段 `scrollTop=300` **确实写进去了**
 * (`screen.scrollH=1144 clientH=844 top=300 ovY=auto`),但**渲染出的图与 scrollY=0 完全一致**。
 * A/B 对照(同组件、同帧、只改 scrollY)输出 SHA256 相同 → Remotion 的截图流程会重置滚动位置。
 *
 * ── 为什么 transform 可行、且必须挂在 `.device-screen > *` 上 ────────────────
 * CSS 变量是**样式**,不像滚动位置那样被截图流程重置(已 A/B 验证:改 scrollY 后
 * 两张图 SHA256 不同)。但初版把 transform 挂在 `.phone-shell` 上 —— 那个节点
 * **只有走 AppShell 的页面才有**(档案/案例库);ChatScreen 与 ActionCardScreen 直挂
 * DeviceFrame,选择器命中 0 个元素,S5/S6 滚动完全失效(独立审查实测 38px vs 名义 731px)。
 * 现在统一挂在 `.device-screen` 的直接子元素上,所有页面都命中。
 *
 * ── 为什么要在这里夹紧,而不是各镜头自己算准 ──────────────────────────────
 * 影片的复刻视图高度可能与真实产品页不同(实测:EmergencyFormView 的 maxScroll=300,
 * 而真实产品页是 344)。拿产品的数字去滚影片的视图就会「差一点没滚到底」。
 * 因此把夹紧收在这一层:调用方给一个「够大」的值即等于「滚到底」,
 * 不需要事先知道正确数字 —— 抗漂移。
 *
 * 代价:sticky 页头不再吸顶(参照系是滚动容器,容器不滚了)。已登记,不假装没有。
 */
function useFilmScroll(scrollY: number): React.RefObject<HTMLDivElement | null> {
  const boxRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const box = boxRef.current;
    if (box === null) return;
    let want = scrollY;
    // ★★ 夹紧要量**真正的滚动容器**(2026-10-07):
    //   对话页(ChatScreen)里溢出发生在 `.film-chat-thread`(它自己 overflow-y:auto,
    //   且在 .film-chat 里是 flex:1、有确定高度),而 `.device-screen` 因为
    //   `.film-chat{height:100%}` 根本不溢出 ⇒ 量它得到的 max 恒为 0,位移永远是 0。
    //   实测后果:S5 的行动卡出现后只露顶部、无论给多大 scrollY 都不动。
    //   注意只在 `.film-chat` 内换用 thread —— S6(ActionCardScreen)也有
    //   `.film-chat-thread`,但那里它的高度是 auto(没有 flex 父级),夹紧会恒为 0,
    //   必须继续走 `.device-screen`。一概而论会把 S6 的滚动改坏。
    const thread = box.querySelector('.film-chat .film-chat-thread');
    const screen = box.querySelector('.device-screen');
    const scroller =
      thread instanceof HTMLElement ? thread : screen instanceof HTMLElement ? screen : null;
    if (scroller !== null) {
      const max = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
      want = Math.min(Math.max(0, scrollY), max);
    }
    box.style.setProperty('--film-scroll', `${String(want)}px`);
  }, [scrollY]);

  return boxRef;
}

export interface DeviceStageProps {
  /** 屏幕区内容:真实产品页面组件(自带 AppShell 或 DeviceFrame) */
  children: React.ReactNode;
  /** 缩放。影片硬约束:背景页面不超过 1.3 倍逻辑尺寸 */
  scale?: number;
  /** 设备外壳中心在画布上的位置 */
  cx?: number;
  cy?: number;
  /** 额外位移 */
  tx?: number;
  ty?: number;
  /**
   * 侧向机位(度)。★ 默认 0 = 现状(正视);非 0 时外层盒建立透视空间。
   * 参数真相来自镜头卡 spotlight-hero-card:rotY 34° 主导 + rotX 仅 8°、persp 1200 —
   * 「侧向水平机位读感优于俯拍」(Q6)。只给确实需要特写的镜头用,不全局套用。
   */
  rotY?: number;
  rotX?: number;
  /** 透视距离(px),只在 rotY/rotX 非 0 时生效。 */
  perspective?: number;
  /**
   * 屏内滚动量(逻辑 px)。
   *
   * ★ 不要凭空写像素:滚动上限应由实测内容高度决定
   *   (见 lib/pageScroll.ts 的 metric,或 element-metrics.json 的元素位置),
   *   否则会滑出内容底部露空白 —— 那正是截图路线的缺陷②。
   */
  scrollY?: number;
  opacity?: number;
}

/** 外壳外框尺寸(390+12×2, 844+12×2)。用于把外壳中心摆到 (cx, cy)。 */
const OUTER_W = 390 + 24;
const OUTER_H = 844 + 24;

/**
 * 摆一台设备并把真实组件放进去,按帧驱动相机与滚动。
 *
 * 前置: 渲染视口宽度 ≥560(见 FILM_VIEWPORT_WIDTH),否则产品外壳不成立
 * 后置: 输出居中的真实产品外壳;屏内内容按 scrollY 位移
 * 异常: 无
 *
 * 滚动实现:见上方 `useFilmScroll` 的长注释 —— 原生 scrollTop 在 Remotion 的
 * 截图流程下不生效(实测),因此用影片自有包装层 + transform。
 */
export const DeviceStage: React.FC<DeviceStageProps> = ({
  children,
  scale = 1,
  cx = 960,
  cy = 540,
  tx = 0,
  ty = 0,
  rotY = 0,
  rotX = 0,
  perspective = 1200,
  scrollY = 0,
  opacity = 1,
}) => {
  const boxRef = useFilmScroll(scrollY);
  const tilted = rotY !== 0 || rotX !== 0;

  return (
    <AbsoluteFill
      style={{
        opacity,
        // ★ 透视建立在外层全幅容器上(不是内层设备盒),于是内层的
        //   translate+scale 仍是 2D 运算、bezel-scan 的边距判据不受影响;
        //   只有 tilted 时才开启 —— 现状七个镜头默认值下渲染逐像素不变。
        perspective: tilted ? perspective : undefined,
        perspectiveOrigin: tilted ? `${String(cx)}px ${String(cy)}px` : undefined,
      }}
    >
      <div
        ref={boxRef}
        style={{
          position: 'absolute',
          left: cx - OUTER_W / 2,
          top: cy - OUTER_H / 2,
          width: OUTER_W,
          height: OUTER_H,
          transform: tilted
            ? `translate(${tx}px, ${ty}px) scale(${scale}) rotateY(${rotY}deg) rotateX(${rotX}deg)`
            : `translate(${tx}px, ${ty}px) scale(${scale})`,
          transformOrigin: 'center center',
          transformStyle: tilted ? 'preserve-3d' : undefined,
          // 位移量以 CSS 变量传给内部的 .film-scroll 包装层
          // @ts-expect-error CSS 自定义属性不在 CSSProperties 类型里
          '--film-scroll': `${String(scrollY)}px`,
        }}
      >
        {children}
      </div>
    </AbsoluteFill>
  );
};

/** 影片根容器:建 .film-root 作用域并注入影片级样式。 */
export const FilmRoot: React.FC<{children: React.ReactNode; bg?: string}> = ({
  children,
  bg = 'var(--bg)',
}) => (
  <AbsoluteFill className="film-root" style={{backgroundColor: bg}}>
    <FilmShellStyles />
    {children}
  </AbsoluteFill>
);
