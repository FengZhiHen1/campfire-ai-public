/**
 * 模块: e2e/support/assertions
 * 职责: 逐页内容断言的求值与证据采集——证明「截图必须有料」而不是只截了一张空态
 * 数据来源:
 *   - docs/证据/orchestrator-20261002-001/T01.md: MUST — 裁决 F（逐页内容断言，且命中特征串进 manifest）
 *   - .dsh/skills/code-craft/references/slices/typescript.md: MUST — TS-09（判别联合用穷尽检查，不留隐式 default）
 * 边界:
 *   - 依赖: @playwright/test 的 Page/expect
 *   - 被依赖: e2e/shots.spec.ts
 * 禁止行为:
 *   - 禁止把断言写成恒真（例如只断言「页面存在」）——它必须能在内容缺失时失败
 *   - 禁止在断言失败时吞掉异常（失败必须让用例失败，不降级成 warning）
 */

import { expect, type Page } from '@playwright/test';

import { RENDER_SETTLE_TIMEOUT_MS } from './paths';

/**
 * 一条内容断言。
 *
 * 三种形态都是「可在图上复核」的：文本串要求逐字出现，计数与正则都给出选择器，
 * 审查者能在对应 PNG 上按同一判据重看一遍。
 */
export type ContentAssertion =
  | {
      kind: 'text';
      /** 这条断言在验证什么（进 manifest，供审查者据图复核）。 */
      intent: string;
      /** 限定作用域的选择器；省略即在整页可见文本里找。 */
      scope?: string;
      /** 需要命中的候选串条数下界。 */
      minHits: number;
      /** 候选特征串（逐字取自设计文档或夹具内容）。 */
      candidates: readonly string[];
    }
  | {
      kind: 'count';
      intent: string;
      /** 被计数的选择器。 */
      selector: string;
      /** 命中数下界。 */
      minCount: number;
    }
  | {
      kind: 'visible';
      intent: string;
      /** 需要可见的选择器（与 count 不同：count 只要求存在于 DOM，visible 要求真的显示出来）。 */
      selector: string;
      /** 可见节点数下界。 */
      minCount: number;
    }
  | {
      kind: 'pattern';
      intent: string;
      /** 被匹配的选择器（取其可见文本）。 */
      selector: string;
      /** 正则源；只写判据所需的形状，不做宽松匹配。 */
      pattern: string;
    };

/** 一条断言的取证结果；`evidence` 即「本次断言命中的内容特征串」。 */
export interface AssertionEvidence {
  intent: string;
  evidence: string;
}

/**
 * 判别联合的穷尽检查；新增形态时这里编译报错，漏处理不可表示（TS-09）。
 *
 * @throws Error 恒定抛出——调用点即「不该到达的分支」
 */
export function assertNever(value: never, message?: string): never {
  throw new Error(message ?? `未处理的判别分支：${JSON.stringify(value)}`);
}

/**
 * 取断言作用域里的可见文本。
 *
 * 用 `allInnerTexts()` 拼接而不是 `innerText()`：后者在定位器命中多个元素时会抛
 * 「strict mode violation」，而本基建的断言作用域天然是多元素（`.list-row`、`summary`）。
 * 拿一个异常当「文本为空」会让失败信息指向错误的方向。
 */
async function scopeText(page: Page, scope: string | undefined): Promise<string> {
  const locator = scope === undefined ? page.locator('body') : page.locator(scope);
  return (await locator.allInnerTexts()).join('\n');
}

/**
 * 轮询读取一个值，直到它满足判据；超时则抛出带诊断上下文的错误。
 *
 * 为什么把四段重复的轮询收在这里：四个断言形态的骨架完全同形——「轮询读取 → 满足判据 →
 * 不满足则用一个形态特有的消息失败」。各写一遍会让「失败信息里要带当前读到的值」这件事
 * 出现四份实现，而它正是断言失败时最有用的那部分。
 *
 * @param read 读取当前值；每次轮询调用一次
 * @param accept 判据；返回真即结束轮询
 * @param describeFailure 判据不满足时的消息构造器；入参是最后一次读到的值。
 *   允许返回 Promise：有的形态要在失败时再补一次读取（如 visible 要补 DOM 总数）。
 * @param pollOptions 轮询选项（超时、失败消息）
 * @returns 判据满足时最后一次读到的值
 * @throws Error 轮询超时——消息由 describeFailure 生成，cause 是原始断言错误
 */
async function pollUntilSatisfied<T>(
  read: () => Promise<T>,
  accept: (value: T) => boolean,
  describeFailure: (latest: T) => string | Promise<string>,
  pollOptions: { timeout: number; message: string },
): Promise<T> {
  let latest: T | undefined;
  try {
    // 轮询的是布尔判据而不是值本身：值域各形态不同（字符串 / 计数 / 正则命中），
    // 而 Playwright 的 poll 只提供通用匹配器；统一收成布尔后四处共用一条实现。
    await expect
      .poll(
        async () => {
          latest = await read();
          return accept(latest);
        },
        pollOptions,
      )
      .toBe(true);
  } catch (error) {
    // latest 一定已被赋值：expect.poll 在超时前至少调用过一次 read。
    // 但仍显式兜一次读取，而不是写 `latest as T` 那样的类型断言——断言失败时
    // 诊断信息里出现假值，比多读一次昂贵得多。
    const value = latest ?? (await read());
    throw new Error(await describeFailure(value), { cause: error });
  }
  return latest ?? (await read());
}

/**
 * 求值一条断言并在失败时给出可诊断的上下文。
 *
 * 前置: page 已导航到目标页且网络夹具已装好
 * 后置: 通过时返回证据串；未通过时抛出（用例失败）
 *
 * @throws Error 断言未通过——消息含断言意图、判据，以及失败时实际读到的文本前 300 字
 *
 * 为什么用 expect.poll 而不是一次性读取：页面是异步渲染的（取数在 effect 里），
 * 一次性读取会把「还没渲染完」误判成「断言恒假」。轮询的上界由 RENDER_SETTLE_TIMEOUT_MS
 * 给出，超时即失败，不会无限等。
 */
export async function evaluateAssertion(page: Page, assertion: ContentAssertion): Promise<AssertionEvidence> {
  const timeout = RENDER_SETTLE_TIMEOUT_MS;
  const failMessage = `内容断言未命中：${assertion.intent}`;

  switch (assertion.kind) {
    case 'text': {
      const candidates = assertion.candidates;
      const hits = (text: string): string[] => candidates.filter((candidate) => text.includes(candidate));
      const latest = await pollUntilSatisfied(
        () => scopeText(page, assertion.scope),
        (text) => hits(text).length >= assertion.minHits,
        (text) =>
          `内容断言未命中：${assertion.intent}\n` +
          `  作用域: ${assertion.scope ?? 'body'}；需要至少 ${String(assertion.minHits)} 条候选串命中\n` +
          `  候选串: ${candidates.join(' | ')}\n` +
          `  失败时读到的文本（前 300 字）: ${text.slice(0, 300)}`,
        { timeout, message: failMessage },
      );
      return { intent: assertion.intent, evidence: hits(latest).join('、') };
    }

    case 'count': {
      const locator = page.locator(assertion.selector);
      const latest = await pollUntilSatisfied(
        () => locator.count(),
        (count) => count >= assertion.minCount,
        (count) =>
          `内容断言未命中：${assertion.intent}\n` +
          `  选择器 ${assertion.selector} 需要至少 ${String(assertion.minCount)} 个，实际 ${String(count)} 个`,
        { timeout, message: failMessage },
      );
      return { intent: assertion.intent, evidence: `${assertion.selector} 命中 ${String(latest)} 个` };
    }

    case 'visible': {
      // count 只要求节点存在于 DOM；本形态额外要求真的显示出来（display/visibility/尺寸三者都成立）。
      // 用 filter({ visible: true }) 而不是逐个下标断言：后者在「可见节点不在最前面」时会误判。
      const visible = page.locator(assertion.selector).filter({ visible: true });
      const latest = await pollUntilSatisfied(
        () => visible.count(),
        (count) => count >= assertion.minCount,
        async (count): Promise<string> => {
          // 诊断信息要能区分「选择器写错了」与「元素在但被隐藏了」，因此补一个 DOM 总数。
          const domTotal = await page.locator(assertion.selector).count();
          return (
            `内容断言未命中：${assertion.intent}\n` +
            `  选择器 ${assertion.selector} 需要至少 ${String(assertion.minCount)} 个可见节点，` +
            `实际可见 ${String(count)} 个（DOM 内共 ${String(domTotal)} 个）`
          );
        },
        { timeout, message: failMessage },
      );
      return { intent: assertion.intent, evidence: `${assertion.selector} 可见 ${String(latest)} 个` };
    }

    case 'pattern': {
      // 与 text 形态同为「多元素作用域」：选择器命中多行时把它们拼起来再匹配。
      // 用 `innerText()` 会在多命中时抛 strict mode violation，把形状问题伪装成「没匹配上」。
      const locator = page.locator(assertion.selector);
      const regex = new RegExp(assertion.pattern);
      let latestText = '';
      const matched = await pollUntilSatisfied(
        async () => {
          latestText = (await locator.allInnerTexts()).join('\n');
          return regex.exec(latestText)?.[0] ?? null;
        },
        (hit) => hit !== null,
        () =>
          `内容断言未命中：${assertion.intent}\n` +
          `  选择器 ${assertion.selector} 的文本未匹配 /${assertion.pattern}/\n` +
          `  失败时读到的文本（前 300 字）: ${latestText.slice(0, 300)}`,
        { timeout, message: failMessage },
      );
      return { intent: assertion.intent, evidence: matched ?? '' };
    }

    default:
      return assertNever(assertion);
  }
}

/**
 * 顺序求值一页的全部断言。
 *
 * 前置: assertions 非空（空数组等于没有内容断言，属于配置错误而不是通过）
 * 后置: 返回与入参同序的证据数组
 *
 * @throws Error 任一断言失败即抛出，后续断言不再求值；断言数组为空也抛出
 */
export async function evaluateAssertions(
  page: Page,
  assertions: readonly ContentAssertion[],
): Promise<AssertionEvidence[]> {
  if (assertions.length === 0) {
    throw new Error('页面配置缺少内容断言：截图必须有料，不允许零断言的页面');
  }
  const evidence: AssertionEvidence[] = [];
  for (const assertion of assertions) {
    evidence.push(await evaluateAssertion(page, assertion));
  }
  return evidence;
}
