// EmergencyFormView —— 应急表单的**帧驱动**视图。
//
// ── 为什么不是直接用 EmergencyFormPage ────────────────────────────────────
// EmergencyFormPage 的题号与作答状态由 useEmergencyForm 内部的 useState 管,
// 没有从外部注入的入口;而影片要求「同一帧永远同一画面」(确定性渲染),
// 靠 effect 去 setState 驱动状态在 Remotion 的多进程渲染下不成立。
// 因此这里复刻它的**视图结构**(逐字对照 EmergencyFormPage 的 JSX)与**题目数据**
// (EMERGENCY_QUESTIONS,真源),把题号与作答改成 props —— 画面完全由帧决定。
//
// ── 为什么 ✓ 一定对齐(修复「√ 位置和复选框没有匹配上」) ─────────────────
// 产品的勾选态由 CSS 驱动:`consultComponents.css` 里
//   .selection:has(input:checked) .check-box { background: accent; … }
// 也就是说 ✓ 与复选框**是同一个 DOM 元素**,不存在「另画一层」的可能。
// 旧版截图路线是在 PNG 上按坐标叠一个 ✓,坐标一猜错就错位 —— 结构性缺陷。
// 本组件渲染真实的 <input type=checkbox checked> + <span class="check-box">,
// 对齐由浏览器布局保证。
import type {EmergencyQuestion} from '../../../../apps/web/src/features/consult/domain/emergency';
import {DeviceFrame} from '../../../../apps/web/src/shared/ui/DeviceFrame';

export interface EmergencyFormViewProps {
  /** 当前题(取自 EMERGENCY_QUESTIONS) */
  question: EmergencyQuestion;
  /** 题号(0-based) */
  index: number;
  /** 总题数 */
  total: number;
  /** 已选选项值 */
  selected: readonly string[];
  /** 自由文本(仅 control === 'text' 的题用) */
  note?: string;
  /** 当前题的补充文本区是否可见 */
  showNote?: boolean;
  /** 已处理题数 */
  handled: number;
  /** 本题已跳过 */
  skipped?: boolean;
  /** 提交中 */
  submitting?: boolean;
  /** 提交按钮是否已按下(用于帧驱动的按压反馈) */
  submitPressed?: boolean;
  /**
   * 未选中项的压暗程度(0..1,帧驱动)。
   *
   * ★ 2026-10-07 新增(镜头卡 chip-grid-single-select-blackout 的语法):
   *   点选之后**其余选项退到背景**,视线落在被选中的那一条上。这是选择类交互的
   *   真实语法(与「给选中项加一圈发光」相反:后者是把注意力平摊给所有元素)。
   *   压暗是**落位后的稳态**,不是持续脉动 —— 只做一次过渡,之后静止。
   */
  unselectedDim?: number;
  /** 选中项的落位回弹(0..1,一次性;0 表示无) */
  checkedPop?: number;
}

/**
 * 渲染应急表单的一屏(与 EmergencyFormPage 同结构)。
 *
 * 前置: question 来自 EMERGENCY_QUESTIONS
 * 后置: 输出 .subpage-head + .tile(题面/进度/选项) + 控制行
 * 异常: 无
 *
 * 注:不套 AppShell —— 调用方(镜头)已经提供设备外壳,和产品里
 * EmergencyFormPage 自行套 AppShell 的差别在此。这样镜头才能统一控制相机。
 */
export const EmergencyFormView: React.FC<EmergencyFormViewProps> = ({
  question,
  index,
  total,
  selected,
  note = '',
  showNote = false,
  handled,
  skipped = false,
  submitting = false,
  submitPressed = false,
  unselectedDim = 0,
  checkedPop = 0,
}) => {
  const progress = (index + 1) / total;

  return (
    // ★ 必须包 DeviceFrame:产品里 EmergencyFormPage 由 AppShell 提供外壳。
    //   漏掉这层就没有 .device/.device-screen,内容失去 390 宽度基准,
    //   题卡会被压成窄条、文字换行错乱(实测踩过)。
    //   这里用 DeviceFrame 而不是 AppShell:应急表单是次级页(产品不渲染 tab 栏)。
    <DeviceFrame>
      <div className="phone-shell">
        <div style={{display: 'flex', flexDirection: 'column', gap: 'var(--space-4)'}}>
      <header className="subpage-head">
        <span className="sp-back">← 退出应急</span>
        <span className="sp-title">现在的情况</span>
      </header>

      <p style={{margin: 0, fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', color: 'var(--muted)'}}>
        跳过 = 未排除，不会当作正常
      </p>

        <section className="tile">
          <div className="step-meta">
            <span className="meta">
              第 {index + 1} / {total} 题
            </span>
            <span className="text-button">上一题</span>
          </div>

          <div className="progress-track" role="progressbar" aria-valuemin={1} aria-valuemax={total} aria-valuenow={index + 1}>
            <div className="progress-fill" style={{width: `${String(progress * 100)}%`}} />
          </div>

          {/* ★ 这里原本写 `className="step-forward"` —— 那是**自造类名**。
              产品的等价规则在 CSS Module 里(`emergencyFormPage.module.css` 的
              `.stepForward`),编译后是带哈希的类名,影片里写 kebab 形式**命中不了**。
              该规则携带两条声明:`display: block` 与题间滑入动画
              (`animation: step-in-forward var(--motion-base)`)。

              影片的取舍:**不补 `display:block`**(外层本就按块级排布,补了也不变),
              **也不补动画** —— 产品那条动画由墙钟驱动,而影片的每一帧必须是 frame 的纯函数
              (见 lib/DeviceStage.tsx 顶部:影片统一关掉了 animation/transition)。
              题间的「换题」观感改由 S4Intake 的切题白闪 + 相机分段推近提供。
              这是**有意偏离**,不是遗漏;但它意味着「题间滑入」这个产品细节在片中没有。
              记录下来,免得后来人以为是漏了。 */}
          <div key={question.key}>
            <h2 className="step-title">{question.prompt}</h2>            <p className="hint">{question.hint}</p>

            <div className="step-options" role="group">
              {question.control === 'text' ? (
                <div className="field">
                  <label htmlFor="film-emergency-note">刚刚发生了什么</label>
                  <textarea
                    id="film-emergency-note"
                    value={note}
                    readOnly
                    placeholder="一两句话就够，写不清也可以跳过。"
                  />
                </div>
              ) : (
                question.options.map((option) => {
                  const checked = selected.includes(option.value);
                  // 压暗只作用于**未选中**项;选中项自己有一次落位回弹。
                  // 两者都是帧驱动的终值(过渡结束后静止),没有 animation/transition。
                  const dim = checked ? 0 : unselectedDim;
                  return (
                    <label
                      className="selection"
                      key={option.value}
                      style={{
                        opacity: 1 - dim * 0.6,
                        transform: checked ? `scale(${String(1 + checkedPop * 0.035)})` : undefined,
                        transformOrigin: 'left center',
                      }}
                    >
                      {/* 真实 input + :has(input:checked) 驱动外观 —— ✓ 与框是同一元素 */}
                      <input
                        type={question.control === 'multi' ? 'checkbox' : 'radio'}
                        name={question.key}
                        value={option.value}
                        checked={checked}
                        readOnly
                      />
                      <span className="check-box" aria-hidden="true" />
                      <span>{option.label}</span>
                    </label>
                  );
                })
              )}
            </div>

            {showNote && question.control !== 'text' ? (
              <div className="field">
                <label htmlFor="film-emergency-extra">补充一句（可选）</label>
                <textarea id="film-emergency-extra" value={note} readOnly placeholder="可以补一句你观察到的样子。" />
              </div>
            ) : null}
          </div>

          {/* ★ 这里原本是 `className="handled-note"` + 行内猜的样式(margin space-3 / color muted)。
              `handled-note` 是**自造类名**(产品用的是 CSS Module 的 `.handledNote`),
              而猜的两个值都与产品**不一致**:
                产品 .handledNote → margin: var(--space-4) top  ; color: var(--meta)
                我原先写的       → margin: var(--space-3) top  ; color: var(--muted)
              即 16px→12px、#57534e→#7a6d63。现在照产品原值写死(不依赖那个不存在的类名)。 */}
          <p style={{margin: 'var(--space-4) 0 0', color: 'var(--meta)', fontSize: 'var(--text-sm)'}}>
            已处理 {handled} / {total} 题
            {skipped ? ' · 本题已跳过（按未排除处理）' : ''}
          </p>
        </section>

        <div style={{display: 'flex', flexDirection: 'column', gap: 'var(--space-3)'}}>
          <div className="button-row">
            <span className="btn btn-quiet">跳过这题</span>
            <span className="btn">下一题</span>
          </div>
          <span
            className="btn btn-primary block"
            style={{
              textAlign: 'center',
              transform: submitPressed ? 'scale(0.97)' : 'scale(1)',
              // ★ 提交态用**降低不透明度**而不是换底色。
              //   产品里按钮的禁用/进行态是 `.btn:disabled { opacity: 0.5 }`
              //   (components.css),底色仍是 accent —— 那是「同一个按钮变淡」,
              //   语义是「还在这个动作上,只是暂时不可再点」。
              //   初版写成 backgroundColor: var(--fg-2)(次级正文色),按钮变成**深褐**,
              //   读起来像「变成了另一个按钮」。独立审查把这条记为保真度偏差。
              opacity: submitting ? 0.55 : 1,
            }}
          >
            {submitting ? '正在提交…' : '提交，开始分析'}
          </span>
          <p className="meta" style={{margin: 0}}>随时提交，无需答完八题。</p>
        </div>
        </div>
      </div>
    </DeviceFrame>
  );
};
