/**
 * 模块: demo/support/roundState
 * 职责: 「这一轮跑完了没有」的判定本身——把判据从「读 DOM」里拆出来，好让它能被测试
 * 数据来源:
 *   - apps/web/demo/support/stack.ts: 原本内联在 `waitRunSettled` 里（本模块是它的判据部分）
 *   - apps/web/src/features/consult/view/ChatWorkspace.tsx: 停止键只在 `thread.isRunning` 时渲染；
 *     发送键在**两种**情形下禁用（运行中、草稿为空）——2026-10-28 实测，见 `GAP-02`
 * 边界:
 *   - 依赖: 无（纯函数 + 一个带计数的小状态机）
 *   - 被依赖: demo/support/stack 的 `waitRunSettled`；测试 `apps/web/tests/demo-round-state.test.ts`
 * 禁止行为:
 *   - 禁止在这里读页面（Playwright 的 Page 不进纯逻辑；DOM 采样留在 stack.ts）
 *   - 禁止把「正文长度没变」单独当成结束：模型在两次工具调用之间会静默十几秒
 *   - 禁止把「有错误卡片」降级成 waiting：模型超时与「还在跑」是两件事，混在一起就只能等到超时
 */

/** 一次采样读到的页面事实。`stack.ts` 负责把它们从 DOM 里读出来。 */
export interface RoundSignals {
  /** 页面错误卡片文案；`null` = 页面上没有 `.error-card`。 */
  errorText: string | null;
  /** 当前 `.msg-doc`（助手正文块）数量。 */
  docCount: number;
  /** 本轮开始前的 `.msg-doc` 数量。 */
  baselineDocs: number;
  /** `data-state="running"` 的工具行数量。 */
  runningTools: number;
  /** 是否有「待作答」的提问卡。 */
  pendingQuestion: boolean;
  /** 停止键是否可见（= 产品认为本轮仍在跑）。 */
  stopVisible: boolean;
  /** 发送键是否禁用（另一种「不能发」，草稿为空时也成立）。 */
  sendDisabled: boolean;
  /** 最后一条正文的字符数（去掉首尾空白）。 */
  lastDocLength: number;
}

/** 单次采样的结论。 */
export type RoundVerdict =
  /** 页面报错：立刻失败，不要等到超时。 */
  | 'error'
  /** 还没结束（或还不能断言结束）。 */
  | 'waiting'
  /** 本轮结束在「等使用者作答」的提问卡上（这是合法终态，不是失败）。 */
  | 'question'
  /** 看起来结束了——但还要过「连续多次不变」的稳定闸门。 */
  | 'stable';

/**
 * 单次采样的判定。
 *
 * 顺序是有意的：错误态最先（否则一个失败的轮次会被当成「还在跑」白等到超时），
 * 其次「本轮还没有新正文」（此时「长度不变」毫无意义），然后是仍在跑的两条证据
 * （工具行、停止键），最后才是长度。
 */
export function classifyRound(signals: RoundSignals): RoundVerdict {
  if (signals.errorText !== null) return 'error';
  if (signals.docCount <= signals.baselineDocs) return 'waiting';
  if (signals.runningTools > 0) return 'waiting';
  // 待作答的提问卡是终态：此时输入区整体收起，发送键必然禁用，不能据此判成「还在跑」。
  if (signals.pendingQuestion) return 'question';
  if (signals.stopVisible) return 'waiting';
  if (signals.sendDisabled) return 'waiting';
  return 'stable';
}

/** 一轮的最终结论（`waitRunSettled` 的返回值）。 */
export type RoundOutcome = 'done' | 'question';

/**
 * 稳定闸门：连续 `stableSamples` 次采样都是「正文长度不变」，才算这一轮真的结束。
 *
 * 为什么还需要这一层：`classifyRound` 只看单帧。模型在两次工具调用之间会静默十几秒，
 * 期间所有「仍在跑」的信号都是干净的；而正文一旦开始增长又会推翻结论。用「连续 N 次
 * 长度不变」把这段静默挡掉（N=4、间隔 3 秒，即至少 12 秒没有新字）。
 */
export class SettleTracker {
  private lastLength = -1;

  private stableCount = 0;

  constructor(private readonly requiredSamples: number) {}

  /** 喂一次采样，拿到当下的结论。`error` 会把错误文案一起带出来（调用方负责抛）。 */
  next(signals: RoundSignals): { kind: 'error'; message: string } | { kind: 'waiting' } | { kind: 'question' } | { kind: 'done' } {
    const verdict = classifyRound(signals);
    if (verdict === 'error') {
      // 错误不受稳定计数影响：一旦出现就是失败，不需要「等它稳定」。
      return { kind: 'error', message: signals.errorText ?? '（读不到错误卡片文案）' };
    }
    if (verdict === 'question') return { kind: 'question' };
    if (verdict === 'waiting') {
      this.reset();
      return { kind: 'waiting' };
    }
    if (this.lastLength !== -1 && signals.lastDocLength === this.lastLength) {
      this.stableCount += 1;
    } else {
      this.stableCount = 1;
      this.lastLength = signals.lastDocLength;
    }
    return this.stableCount >= this.requiredSamples ? { kind: 'done' } : { kind: 'waiting' };
  }

  private reset(): void {
    this.lastLength = -1;
    this.stableCount = 0;
  }
}
