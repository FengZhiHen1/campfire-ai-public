/**
 * 模块: shared/ui/DeviceFrame
 * 职责: 宽视口下的设备外壳——把页面内容装进一台「手机」的屏幕区
 * 数据来源:
 *   - docs/design/DESIGN.md: MUST — 布局与 posture 要点（手机蒙版 + 宽视口设备外壳）
 *   - apps/web/src/shared/styles/global.css: MUST — .device-stage / .device / .device-screen 的几何与断点
 * 边界:
 *   - 依赖: 无（纯渲染容器，不取数、不读写全局状态、不注册副作用）
 *   - 被依赖: shared/ui/AppShell 与 features/accounts/view/LoginPage
 * 禁止行为:
 *   - 禁止在页面层写外壳几何（几何归 global.css 的设备外壳段落，本组件只出结构与类名）
 *   - 禁止给三层包裹加 role / aria-*：窄视口下它们退化为 display: contents，
 *     带语义的元素在该形态下会从无障碍树中消失
 */

import type { ReactNode } from 'react';

/** DeviceFrame props。 */
export interface DeviceFrameProps {
  /** 屏幕区内容；页面容器与底部导航由调用方放进这里。 */
  children: ReactNode;
}

/**
 * 渲染设备外壳的三层结构（舞台 → 外壳 → 屏幕区）。
 *
 * 前置: 无
 * 后置: 输出 .device-stage > .device > .device-screen，children 落在屏幕区内
 * 异常: 无
 *
 * 屏幕区是外壳内唯一的滚动容器
 *
 * 宽视口下 .device-screen 带固定高与 overflow-y: auto，页面滚动因此发生在屏幕区内
 * 而不是文档级——这是「像在一台手机里操作」的关键：内容高了只在屏幕里滚，
 * 外壳与舞台不动。
 *
 * 为什么外壳层数固定为三
 *
 * 定位上下文必须落在外壳（.device）而不是屏幕区（.device-screen）：屏幕区是滚动
 * 容器，若 fixed 后代的包含块是它，滚动时底部导航会跟着内容走。舞台层则承担居中
 * 与视口高。三者的具体声明见 global.css 的设备外壳段落。
 */
export function DeviceFrame({ children }: DeviceFrameProps) {
  return (
    <div className="device-stage">
      <div className="device">
        <div className="device-screen">{children}</div>
      </div>
    </div>
  );
}
