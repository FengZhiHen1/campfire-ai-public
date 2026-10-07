// ChatScreen —— 对话页外壳:把流式消息块放进真实产品的对话页结构里。
//
// ── 为什么不用 ChatWorkspace ─────────────────────────────────────────────
// ChatWorkspace 依赖 assistant-ui runtime + zustand store + SSE 端口。影片要求
// **确定性**(同一帧永远同一画面),而真实 runtime 的时间线由网络驱动、无法回放。
// 因此本文件复用它的**视图结构与契约类名**(逐字对照其 JSX),消息内容改为帧驱动:
// 观感与真实产品一致,但完全可回放。
//
// DOM 结构对照 ChatWorkspace:
//   .workspace
//     ├ header.subpage-head   (← 咨询 / 咨询 / 技能标签)
//     ├ div.thread            (消息流,内部滚动)
//     └ div.footer            (输入区,贴底)
//         └ form.chat-compose ( textarea + 发送按钮 )
//             + p.meta
//
// 样式全部来自 chatPage.module.css 与 consultComponents.css(真源),本文件不写视觉。
import type {ReactNode} from 'react';

import {DeviceFrame} from '../../../../apps/web/src/shared/ui/DeviceFrame';

/**
 * 对话屏:页头 + 消息流 + 底部输入区。
 *
 * ★ 必须包 DeviceFrame:产品里对话页由 ChatWorkspace 直挂 `<DeviceFrame>`
 *   (它不套 AppShell —— 对话是满幅画布)。漏掉这层就没有 `.device/.device-screen`,
 *   外壳与屏幕区都不存在,画面变成「裸内容」(实测踩过)。
 *
 * 高度说明:产品里 .workspace 靠 `height:100%` 在外壳内撑满 844。影片的容器链
 * 多了我们自己的 translateY 包装层,百分比高度不会自动传递,因此这里显式给 844
 * —— 与屏幕区同高。这是唯一能让消息流内部滚动、且输入区贴屏幕底边的办法。
 */
export const ChatScreen: React.FC<{
  children: ReactNode;
  skillLabels?: readonly string[];
  /** 输入框文案 */
  placeholder?: string;
  /** 输入区下方的提示行 */
  footerHint?: string;
}> = ({children, skillLabels = [], placeholder = '写下你想补充的情况……', footerHint}) => (
  <DeviceFrame>
    <div
      className="film-chat"
      style={{background: 'var(--bg)'}}
    >
      <header className="subpage-head">
        <span className="sp-back">← 咨询</span>
        <span className="sp-title">咨询</span>
        {skillLabels.length > 0 ? (
          <span className="tag meta sp-tag">{`技能 ${String(skillLabels.length)} 个`}</span>
        ) : null}
      </header>

      <div className="film-chat-thread">{children}</div>

      <div className="film-chat-footer">
        <form className="chat-compose" onSubmit={(e) => e.preventDefault()}>
          <label className="sr-only" htmlFor="film-composer">
            发送消息
          </label>
          <textarea id="film-composer" rows={1} placeholder={placeholder} readOnly value="" />
          <button className="btn btn-primary" type="button" disabled>
            发送
          </button>
        </form>
        {footerHint === undefined ? null : <p className="meta">{footerHint}</p>}
      </div>
    </div>
  </DeviceFrame>
);
