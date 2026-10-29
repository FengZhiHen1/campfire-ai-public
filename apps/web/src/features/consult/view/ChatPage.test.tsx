/**
 * 模块: features/consult/view/ChatPage.test
 * 职责: 对话页的组件用例——对照技术设计第 8 节验证清单逐条
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 8 节（组件测试清单）
 *   - docs/design/pages/对话页.md: MUST — 状态覆盖表与契约修订 1～8
 * 边界:
 *   - 依赖: view/ChatPage、test/{fixtures,consultPortStub}、viewModel/runStore
 *   - 被依赖: 无（回归守卫）
 * 禁止行为:
 *   - 禁止断言守卫等于授权
 *   - 禁止接真实后端（端口以替身注入；真实联调在 T12 后）
 *
 * 为什么用 MemoryRouter + Routes 而不是 createMemoryRouter：T09 实测 jsdom 与 data router
 * 不兼容（构造 Request 时 AbortSignal 类身份错误）。
 * 为什么用 fireEvent 而不是 user-event：本包未安装 user-event（依赖纪律），
 * fireEvent 的 change/click/submit 足够驱动本页。
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ChatPage } from './ChatPage';
import { ConsultError } from '../domain/errors';
import { createConsultPortStub, type ConsultPortStub } from '../test/consultPortStub';
import { resetConsultRunStore, useRunStore } from '../viewModel/runStore';
import {
  actionCardEvent,
  citation,
  hydratedAssistant,
  historyResponse,
  questionEvent,
  QUESTION_ITEMS,
  runFailed,
  runFinished,
  runStarted,
  textDelta,
} from '../test/fixtures';
import type { ListMessagesResponse } from '../../../shared/types/consult';

/** 渲染对话页（路由参数走真实的 useParams）。 */
function renderChat(port: ConsultPortStub, entry: { path?: string; state?: unknown } = {}) {
  const path = entry.path ?? '/consult/sessions/s1';
  const initialEntry = entry.state === undefined ? path : { pathname: path, state: entry.state };
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/consult/sessions/:sessionId" element={<ChatPage consult={port} />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** 永不落定的 promise（loading 态断言用）。 */
function pending<T>(): Promise<T> {
  return new Promise<T>(() => undefined);
}

/** 在输入框写一条消息并发送。 */
async function send(text: string): Promise<void> {
  const box = await screen.findByLabelText('发送消息');
  fireEvent.change(box, { target: { value: text } });
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
  });
}

beforeEach(() => {
  resetConsultRunStore();
});

describe('对话页 — 历史水合三态', () => {
  it('水合中显示同形骨架与载入文案（不显示空对话）', async () => {
    const port = createConsultPortStub();
    vi.mocked(port.loadHistory).mockReturnValue(pending<ListMessagesResponse>());
    renderChat(port);

    expect(screen.getByText('正在载入这段对话…')).toBeDefined();
    expect(document.querySelectorAll('.skeleton').length).toBeGreaterThan(0);
    expect(screen.queryByLabelText('发送消息')).toBeNull();
  });

  it('水合失败显示错误与重试，不显示空对话；重试成功后渲染消息', async () => {
    const port = createConsultPortStub();
    vi.mocked(port.loadHistory).mockRejectedValueOnce(new ConsultError('unavailable', '服务暂时不可用'));
    renderChat(port);

    expect(await screen.findByText('服务暂时不可用')).toBeDefined();
    expect(screen.queryByLabelText('发送消息')).toBeNull();

    vi.mocked(port.loadHistory).mockResolvedValue(
      historyResponse([hydratedAssistant('m1', [{ type: 'text', text: '历史回答' }])]),
    );
    fireEvent.click(screen.getByRole('button', { name: '重试' }));

    expect(await screen.findByText('历史回答')).toBeDefined();
    expect(screen.getByLabelText('发送消息')).toBeDefined();
  });

  it('历史里【已作答】的提问是只读记录（不接受再次作答）', async () => {
    const port = createConsultPortStub({
      history: historyResponse([
        hydratedAssistant('m1', [
          { type: 'question-record', batch_id: 'b1', items: [...QUESTION_ITEMS], answered: true },
        ]),
      ]),
    });
    renderChat(port);

    // ★ 措辞判据（T27 修正 / T31 沿革）：服务端判为已作答 ⇒ 只读。
    expect(await screen.findByText('这是当时向你提出的问题，当时的作答见对话里的相关消息。')).toBeDefined();
    expect(screen.getByText('提问记录')).toBeDefined();
    // 反空断言：旧的失实措辞必须不再出现（否则这次修正等于没做）。
    expect(screen.queryByText('这组问题已经处理过，记录如下（回答见当时的对话）。')).toBeNull();
    expect(screen.queryByText('已提交')).toBeNull();
    expect(screen.queryByRole('button', { name: '提交' })).toBeNull();
  });

  it('历史里【无法判定】的提问也只读（fail-closed）', async () => {
    const port = createConsultPortStub({
      history: historyResponse([
        hydratedAssistant('m1', [
          { type: 'question-record', batch_id: 'b1', items: [...QUESTION_ITEMS], answered: null },
        ]),
      ]),
    });
    renderChat(port);

    // 判不出来 ⇒ 只读记录（猜成可作答会让使用者重复作答）。
    expect(await screen.findByText('这是当时向你提出的问题，当时的作答见对话里的相关消息。')).toBeDefined();
    expect(screen.queryByRole('button', { name: '提交' })).toBeNull();
  });

  it('★ 历史里【未作答】的提问可以补答（本包修的那条）', async () => {
    const port = createConsultPortStub({
      history: historyResponse([
        hydratedAssistant('m1', [
          { type: 'question-record', batch_id: 'b1', items: [...QUESTION_ITEMS], answered: false },
        ]),
      ]),
    });
    renderChat(port);

    // 刷新后提问卡必须仍然可作答：题干在，且卡是可交互的（选项 + 下一题）。
    // 首题不是末题，因此这里出现的是「下一题」而不是「提交」——提交按钮在末题上。
    expect(await screen.findByText(QUESTION_ITEMS[0]?.prompt ?? '')).toBeDefined();
    expect(screen.getByRole('button', { name: /可以/ })).toBeDefined();
    expect(screen.getByRole('button', { name: '下一题' })).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    expect(screen.getByRole('button', { name: '提交' })).toBeDefined();
    // 中性措辞不得出现（那是「静态记录」态的文案）。
    expect(screen.queryByText('提问记录')).toBeNull();
  });

  it('★ 两张历史卡都可作答时，自由回答输入框的 id 不重复（T31 引入的可达缺陷）', async () => {
    // 背景：T31 之前历史卡一律 `mode='record'` ⇒ 同一条消息流里最多只有一张卡可作答，
    // 因此输入框 id 用 `${mode}-${题标识}` 拼是安全的。T31 让每张未作答的历史卡都可作答，
    // 于是「同一条会话里两组题都未作答」会让两张卡拼出同一个 id ⇒ 第二张卡的 `<label for>`
    // 指到第一张卡的 textarea。改用 `useId()` 后每个实例唯一。
    const port = createConsultPortStub({
      history: historyResponse([
        hydratedAssistant('m1', [
          { type: 'question-record', batch_id: 'b1', items: [...QUESTION_ITEMS], answered: false },
        ]),
        hydratedAssistant('m2', [
          { type: 'question-record', batch_id: 'b2', items: [...QUESTION_ITEMS], answered: false },
        ]),
      ]),
    });
    renderChat(port);

    // 两张卡的题面相同 ⇒ 用 findAllByText（findByText 会因命中两个而报错）。
    const titles = await screen.findAllByText(QUESTION_ITEMS[0]?.prompt ?? '');
    expect(titles).toHaveLength(2);
    const toggles = screen.getAllByRole('button', { name: /用自己的话回答/ });
    expect(toggles).toHaveLength(2);
    // 两张卡都展开自由回答通道
    for (const toggle of toggles) fireEvent.click(toggle);

    const boxes = Array.from(document.querySelectorAll('.question-card textarea'));
    expect(boxes).toHaveLength(2);
    const ids = boxes.map((box) => box.id);
    expect(ids.every((id) => id !== '')).toBe(true);
    expect(new Set(ids).size).toBe(2); // ★ 唯一性：重复会让 label 指错输入框

    // 每个 label 的 htmlFor 必须指向同一条卡里的 textarea（而不是另一张卡的）。
    for (const box of boxes) {
      const card = box.closest('.question-card');
      const label = card?.querySelector('label');
      expect(label?.htmlFor).toBe(box.id);
    }
  });
});

describe('对话页 — 跳过一次性引导（BUG-03 的入口）', () => {
  beforeEach(() => {
    // 入口的「刷新后仍可见」依赖会话级记忆；用例之间必须清干净，否则先跑的用例会把标记带给下一个。
    window.sessionStorage.clear();
  });

  it('建会话时说引导待注入 ⇒ 页头出现「跳过引导」，点它调到端口并撤掉入口', async () => {
    const port = createConsultPortStub({ history: historyResponse([hydratedAssistant('m1', [])]) });
    renderChat(port, { state: { guidePending: true } });

    const skip = await screen.findByRole('button', { name: '跳过引导' });
    expect(port.skipCalls).toEqual([]);

    await act(async () => {
      fireEvent.click(skip);
    });

    expect(port.skipCalls, '跳过必须真的打到端口（契约第 6 节）').toEqual(['s1']);
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '跳过引导' })).toBeNull();
    });
  });

  it('没有「引导待注入」这回事时不显示入口（不许无来源地挂着）', async () => {
    const port = createConsultPortStub({ history: historyResponse([hydratedAssistant('m1', [])]) });
    renderChat(port);

    await screen.findByLabelText('发送消息');
    expect(screen.queryByRole('button', { name: '跳过引导' })).toBeNull();
  });

  it('引导已完成（流里有 finish_onboarding 工具行）⇒ 不再显示入口', async () => {
    const port = createConsultPortStub({
      history: historyResponse([
        // 线格式的 tool_call part（契约第 7 节）：`tool_name` 是协议字段，水合时被转成
        // 视图层的 `{type:'data', name:'tool-call'}`。断言入口隐藏要基于**这条**真实形状。
        hydratedAssistant('m1', [{ type: 'tool_call', tool_name: 'finish_onboarding', ok: true, summary: '' }]),
      ]),
    });
    renderChat(port, { state: { guidePending: true } });

    await screen.findByLabelText('发送消息');
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '跳过引导' })).toBeNull();
    });
  });

  it('跳过失败 ⇒ 入口留着并说明原因（不得表现成已跳过）', async () => {
    const port = createConsultPortStub({
      history: historyResponse([hydratedAssistant('m1', [])]),
      skipError: new ConsultError('network', '网络中断'),
    });
    renderChat(port, { state: { guidePending: true } });

    const skip = await screen.findByRole('button', { name: '跳过引导' });
    await act(async () => {
      fireEvent.click(skip);
    });

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('跳过引导没有成功');
    });
    expect(screen.getByRole('button', { name: '跳过引导' })).toBeDefined();
  });

  it('刷新后入口仍在（会话级记忆）：路由 state 丢了也不该让引导变成不可跳过', async () => {
    window.sessionStorage.setItem('consult.guidePending.s1', '1');
    const port = createConsultPortStub({ history: historyResponse([hydratedAssistant('m1', [])]) });
    renderChat(port);

    expect(await screen.findByRole('button', { name: '跳过引导' })).toBeDefined();
  });
});

describe('对话页 — 依据区（citation）', () => {
  it('默认收起；展开后含标题与来源（reference 无库别前缀 ⇒ 如实不给跳转）', async () => {
    const port = createConsultPortStub({
      history: historyResponse([
        hydratedAssistant('m1', [{ type: 'text', text: '历史回答' }, { type: 'citation', citation: citation() }]),
      ]),
    });
    renderChat(port);

    const summary = await screen.findByText('依据 1 条');
    const details = summary.closest('details');
    expect(details?.hasAttribute('open')).toBe(false);
    // 标题取 `summary`（后端写入摘要时取的就是条目标题——它是使用者一眼认出那条来源的最短信息）；
    // `reference` 不再是标题，因此这里断言的是摘要文本，而不是旧的「把 reference 当标题显示」。
    expect(screen.getByText('样例记录提到，等候区里人多且声音较大。')).toBeDefined();
    const meta = document.querySelector('.citation-item .citation-source')?.textContent ?? '';
    expect(meta).toContain('来源：项目内虚构资料');
    // 这条 fixture 的 `reference` 是纯标题、没有 `<库别>:` 前缀 ⇒ **不该**给出跳转，
    // 并且要如实说明（猜错库比不跳转更糟）。
    expect(meta).toContain('暂不能跳转');
    expect(document.querySelector('.citation-item a.citation-title')).toBeNull();

    fireEvent.click(summary);
    expect(summary.closest('details')?.hasAttribute('open')).toBe(true);
  });
});

describe('对话页 — 提问卡（活卡）', () => {
  /** 让服务端「提出一组问题」并把运行跑完。 */
  async function askQuestions(): Promise<ConsultPortStub> {
    const port = createConsultPortStub({ history: historyResponse([]) });
    port.script([runStarted(), questionEvent(QUESTION_ITEMS), runFinished()]);
    renderChat(port);
    await send('先把情况说一遍');
    await screen.findByText(QUESTION_ITEMS[0]?.prompt ?? '');
    return port;
  }

  it('待作答时收起输入区（草稿与技能选择保留），逐题作答并整组一次提交', async () => {
    const port = await askQuestions();

    // 输入区互斥：题干出现后输入框消失。
    expect(screen.queryByLabelText('发送消息')).toBeNull();

    // 选项通道暂存；切到第二题再回来仍保留（逐题切换保留答案）。
    fireEvent.click(screen.getByRole('button', { name: /可以/ }));
    fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    fireEvent.click(screen.getByRole('button', { name: '上一题' }));
    expect(screen.getByRole('button', { name: /可以/ }).getAttribute('aria-pressed')).toBe('true');

    // 第二题不可跳过，且未完成时提交按钮禁用。
    fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    expect(screen.getByRole('button', { name: '跳过' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('button', { name: '提交' }).hasAttribute('disabled')).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: /不确定/ }));
    const submit = screen.getByRole('button', { name: '提交' });
    expect(submit.hasAttribute('disabled')).toBe(false);

    await act(async () => {
      fireEvent.click(submit);
    });

    // 整组一次提交：第二次 POST 走 answers 形态。
    await waitFor(() => expect(port.sendCalls).toHaveLength(2));
    expect(port.sendCalls[1]?.payload).toEqual({
      answers: [
        { id: 'q1', value: '可以' },
        { id: 'q2', value: '不确定' },
      ],
      // ★ 出网键名逐字 snake_case；值 = 这一组的 batchId（askQuestions 用的是 questionEvent 的 b1）。
      batch_id: 'b1',
      skill: null,
      client_message_id: expect.any(String),
    });
    // 实际序列化后的文本（不是内存对象）：键名以 JSON 字节为准，且不得漏出内部名 batchId。
    expect(JSON.stringify(port.sendCalls[1]?.payload)).toContain('"batch_id":"b1"');
    expect(JSON.stringify(port.sendCalls[1]?.payload)).not.toContain('batchId');

    // 提交后成为静态已提交记录，输入区恢复。
    expect(await screen.findByText('整组已提交，不能再修改。')).toBeDefined();
    expect(screen.queryByRole('button', { name: '提交' })).toBeNull();
    expect(await screen.findByLabelText('发送消息')).toBeDefined();
  });

  it('★ 多组题：先提交第二组再提交第一组，各次载荷带的是【自己那一组】的 batch_id', async () => {
    // 判别力设计（本包最关键的一条）：两组提问同时可作答，先提交后一组、再提交前一组。
    // 若实现把 batchId 取成「最后一次 question 事件的批次」（全局指针/陈旧闭包旧值），
    // 两次载荷会带同一个 id ⇒ 本用例变红。两组 id 不同且顺序被打乱，因此「恰好蒙对」不可能。
    const port = createConsultPortStub({ history: historyResponse([]) });
    port.script([
      runStarted(),
      questionEvent(QUESTION_ITEMS, 'b1'),
      questionEvent(QUESTION_ITEMS, 'b2'),
      runFinished(),
    ]);
    renderChat(port);
    await send('先把情况说一遍');
    await waitFor(() => expect(document.querySelectorAll('.question-card')).toHaveLength(2));

    /** 在指定序号的提问卡内完成作答并提交。 */
    const answerAndSubmit = async (cardIndex: number): Promise<void> => {
      const card = document.querySelectorAll('.question-card')[cardIndex];
      if (card === null || card === undefined) throw new Error(`第 ${cardIndex} 张提问卡不存在`);
      const clickIn = (name: string | RegExp): void => {
        const button = Array.from(card.querySelectorAll('button')).find((candidate) =>
          typeof name === 'string' ? candidate.textContent === name : name.test(candidate.textContent ?? ''),
        );
        if (button === undefined) throw new Error(`卡内找不到按钮 ${String(name)}`);
        fireEvent.click(button);
      };
      clickIn(/可以/);
      clickIn('下一题');
      clickIn(/不确定/);
      await act(async () => {
        clickIn('提交');
      });
    };

    await answerAndSubmit(1); // 先提交第二组
    await waitFor(() => expect(port.sendCalls).toHaveLength(2));
    await answerAndSubmit(0); // 再提交第一组
    await waitFor(() => expect(port.sendCalls).toHaveLength(3));

    const second = port.sendCalls[1]?.payload as { batch_id?: string };
    const first = port.sendCalls[2]?.payload as { batch_id?: string };
    expect(second.batch_id).toBe('b2');
    expect(first.batch_id).toBe('b1');
    // 陈旧旧值/全局指针形态的对照：那会让两次载荷带同一个 id。这里显式钉住「必须不同」。
    expect(second.batch_id).not.toBe(first.batch_id);
  });

  it('跳过通道写入显式「（跳过）」记录，未提交时草稿留在卡上', async () => {
    const port = await askQuestions();

    fireEvent.click(screen.getByRole('button', { name: '跳过' }));
    expect(screen.getByText(/本题已跳过（未排除）/)).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: '下一题' }));
    fireEvent.click(screen.getByRole('button', { name: /不确定/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '提交' }));
    });

    await waitFor(() => expect(port.sendCalls).toHaveLength(2));
    // 跳过的题按 skipped 上报（不带 value）——服务端据此判「未排除」。
    expect(port.sendCalls[1]?.payload).toMatchObject({
      answers: [
        { id: 'q1', skipped: true },
        { id: 'q2', value: '不确定' },
      ],
    });
    expect(await screen.findByText('（跳过）')).toBeDefined();
  });
});

describe('对话页 — 行动卡', () => {
  async function runWith(cards: ReturnType<typeof actionCardEvent>[]): Promise<ConsultPortStub> {
    const port = createConsultPortStub({ history: historyResponse([]) });
    port.script([runStarted(['emergency-consulting']), ...cards, textDelta('补充一句'), runFinished()]);
    renderChat(port);
    await send('他突然捂住耳朵');
    return port;
  }

  it('七节分区渲染、医疗风险徽章与来源/置信标注', async () => {
    await runWith([actionCardEvent()]);

    expect(await screen.findByText('现场行动卡')).toBeDefined();
    expect(document.querySelectorAll('.ac-section')).toHaveLength(7);
    expect(document.querySelectorAll('.ac-head')).toHaveLength(7);
    expect(document.querySelector('.status.unruled')?.textContent).toBe('医疗风险 · 未排除');
    const sources = Array.from(document.querySelectorAll('.ac-source')).map((node) => node.textContent ?? '');
    expect(sources).toContain('来源：家属报告 · 置信：较可能');
    expect(sources).toContain('来源：AI 推断 · 置信：可能');
    // 「立即做」是唯一的优先级节，并渲染「现在先看」块。
    expect(document.querySelectorAll('.ac-section.now')).toHaveLength(1);
    expect(document.querySelector('.chat-action-priority')?.textContent).toContain('现在先看 · 立即做');
  });

  it('medical_risk 越界载荷被拒渲染（不显示成一张看起来合法的卡）', async () => {
    await runWith([actionCardEvent({ states: [{ key: 'medical_risk', value: 'critical' }] })]);

    expect(await screen.findByText('这张行动卡没有显示')).toBeDefined();
    expect(document.querySelectorAll('.ac-section')).toHaveLength(0);
  });

  it('重复评估：旧卡标失效并保留（不删除、不打补丁）', async () => {
    await runWith([actionCardEvent({ card_id: 'card-1' }), actionCardEvent({ card_id: 'card-2' })]);

    expect(await screen.findByText('已过期，见最新卡片')).toBeDefined();
    expect(document.querySelectorAll('.action-card')).toHaveLength(2);
    expect(document.querySelectorAll('.action-card.expired')).toHaveLength(1);
  });
});

describe('对话页 — 思考区与工具行', () => {
  it('思考默认收起、内容在折叠区内，不作为正文', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    port.script([
      runStarted(),
      { type: 'reasoning_delta', delta: '我在核对情境' },
      textDelta('这是正文回答。'),
      runFinished(),
    ]);
    renderChat(port);
    await send('先看看');

    expect(await screen.findByText('这是正文回答。')).toBeDefined();
    const row = document.querySelector('details.reasoning-row');
    expect(row?.hasAttribute('open')).toBe(false);
    expect(row?.querySelector('.process-body')?.textContent).toContain('我在核对情境');
    const bodyParagraphs = Array.from(document.querySelectorAll('.msg-doc > p')).map((node) => node.textContent ?? '');
    expect(bodyParagraphs.some((text) => text.includes('我在核对情境'))).toBe(false);
  });

  it('应急场景的思考行收为一行「分析说明 · 已结束」', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    port.script([runStarted(['emergency-consulting']), { type: 'reasoning_delta', delta: '核对中' }, runFinished()]);
    renderChat(port);
    await send('应急');

    expect(await screen.findByText('分析说明 · 已结束')).toBeDefined();
  });

  it('工具调用行默认收起并显示名称与摘要', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    port.script([
      runStarted(),
      { type: 'tool_call_started', tool_name: 'search_knowledge', call_id: 'c1' },
      { type: 'tool_call_finished', tool_name: 'search_knowledge', call_id: 'c1', ok: true, error_code: null, summary: '找到 2 条' },
      runFinished(),
    ]);
    renderChat(port);
    await send('查一下');

    const row = await waitFor(() => {
      const node = document.querySelector('details.tool-row');
      if (node === null) throw new Error('工具行还没渲染');
      return node;
    });
    expect(row.hasAttribute('open')).toBe(false);
    // OBS-01：工具行显示面向使用者的中文名，不显示线上标识符（设计真源：对话页.md:60）。
    expect(row.textContent).toContain('查阅资料 · 已结束');
    expect(row.textContent).not.toContain('search_knowledge');
    expect(row.textContent).toContain('找到 2 条');
  });

  it('未加映射的工具名走中性兜底，仍不把标识符显示给使用者', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    port.script([
      runStarted(),
      { type: 'tool_call_started', tool_name: 'a_brand_new_tool', call_id: 'c1' },
      { type: 'tool_call_finished', tool_name: 'a_brand_new_tool', call_id: 'c1', ok: true, error_code: null, summary: '完成' },
      runFinished(),
    ]);
    renderChat(port);
    await send('试一下');

    const row = await waitFor(() => {
      const node = document.querySelector('details.tool-row');
      if (node === null) throw new Error('工具行还没渲染');
      return node;
    });
    // 兜底文案 + 状态后缀；标识符一个字母都不露出（这正是 OBS-01 的形态）。
    expect(row.textContent).toContain('其他操作 · 已结束');
    expect(row.textContent).not.toContain('a_brand_new_tool');
  });

  it('OBS-01 原始形态：失败的工具行显示「建立支持对象 · 未完成」，不再是 create_support_object', async () => {
    // 测试人员报告里的原话是 `create_support_object · 未完成`（建档失败那一张卡）。
    const port = createConsultPortStub({ history: historyResponse([]) });
    port.script([
      runStarted(['onboarding']),
      { type: 'tool_call_started', tool_name: 'create_support_object', call_id: 'c1' },
      {
        type: 'tool_call_finished',
        tool_name: 'create_support_object',
        call_id: 'c1',
        ok: false,
        error_code: 'tool_failed',
        summary: '缺少登录账号',
      },
      runFinished(),
    ]);
    renderChat(port);
    await send('建档');

    const row = await waitFor(() => {
      const node = document.querySelector('details.tool-row');
      if (node === null) throw new Error('工具行还没渲染');
      return node;
    });
    expect(row.textContent).toContain('建立支持对象 · 未完成');
    expect(row.textContent).not.toContain('create_support_object');
  });
});

describe('对话页 — 运行状态与失败语义', () => {
  it('progress 文案进状态条', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    renderChat(port);
    await screen.findByLabelText('发送消息');

    // 直接驱动状态：脚本化事件流是一次性消费的，progress 与 run_finished 在同一批
    // 微任务里到达，断言不到「中间那一帧」。事件→状态的映射由 chatAdapter/runStore 用例覆盖，
    // 这里只需验证状态条确实读 progressText。
    act(() => {
      useRunStore.getState().applyRunEvent({ type: 'progress', message: '正在检索资料…' });
    });

    expect(await screen.findByText('正在检索资料…')).toBeDefined();
  });

  it('run_failed：保留已渲染文字并显示原因（检索类失败不写「未找到相关内容」）', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    port.script([runStarted(), textDelta('已经写了一半'), runFailed('injection_failed')]);
    renderChat(port);
    await send('帮我看看');

    expect(await screen.findByText('检索暂时不可用')).toBeDefined();
    expect(screen.getByText('已经写了一半')).toBeDefined();
    expect(screen.queryByText(/未找到相关内容/)).toBeNull();
    expect(screen.getByRole('button', { name: '重试' })).toBeDefined();
  });

  it('断连期间状态条显示「连接中断，正在重连」', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    renderChat(port);
    await screen.findByLabelText('发送消息');

    act(() => {
      useRunStore.getState().setConnection('reconnecting');
    });

    expect(await screen.findByText('连接中断，正在重连')).toBeDefined();
  });

  it('取消后标「本次回答中断」并显示停止按钮仅在运行中', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    renderChat(port);
    await screen.findByLabelText('发送消息');
    expect(screen.queryByRole('button', { name: '停止' })).toBeNull();

    act(() => {
      useRunStore.getState().applyRunEvent(runStarted());
      useRunStore.getState().markInterrupted();
    });

    expect(await screen.findByText('本次回答中断')).toBeDefined();
  });
});

describe('对话页 — 技能选择器', () => {
  it('发送即消费：选择只作用于下一条消息，发送后回归「自动」', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    port.script([runStarted(['daily-consulting']), textDelta('好的'), runFinished()]);
    renderChat(port);
    await screen.findByLabelText('发送消息');

    fireEvent.click(screen.getByRole('button', { name: '日常咨询' }));
    expect(screen.getByRole('button', { name: '日常咨询' }).getAttribute('aria-pressed')).toBe('true');

    await send('他最近总是睡不好');

    await waitFor(() => expect(port.sendCalls).toHaveLength(1));
    expect(port.sendCalls[0]?.payload).toMatchObject({ skill: 'daily-consulting' });
    await waitFor(() => expect(useRunStore.getState().peekPendingSkill()).toBeNull());
    expect(screen.getByRole('button', { name: '自动' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('应急不在选择器里（值域裁决：应急只走表单入口，skill 参数传它回 422）', () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    renderChat(port);

    expect(screen.queryByRole('button', { name: '应急咨询' })).toBeNull();
  });

  it('多技能生效集合在页头串联展示（历史推导 ∪ 本轮新增）', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    port.script([runStarted(['daily-consulting', 'profile-curation']), textDelta('好'), runFinished()]);
    renderChat(port);
    await screen.findByLabelText('发送消息');

    await send('整理一下刚才说的');

    expect((await screen.findAllByText('日常咨询')).length).toBeGreaterThan(0);
    expect((await screen.findAllByText('档案整理')).length).toBeGreaterThan(0);
  });
});

describe('对话页 — 页头技能标签折叠（授权语义：宽度不足时整体折叠为「技能 N 个」）', () => {
  /**
   * 取页头里的技能标签文本。
   *
   * 必须限定在 .subpage-head 内：SkillPicker 的 chip 用的是同一批中文技能名，
   * 全局查询会把选择器的 chip 也算进来，断言便不再指向页头（假阳性）。
   */
  const headTagTexts = (container: HTMLElement): string[] =>
    Array.from(container.querySelectorAll('.subpage-head .sp-tag')).map((el) => el.textContent ?? '');

  /** 直接写入生效技能集合（run_started 的等价路径，与 line 347 同法）。 */
  const setActiveSkills = (ids: readonly string[]): void => {
    act(() => {
      useRunStore.getState().applyRunEvent(runStarted(ids));
    });
  };

  it('非折叠态：3 个标签仍逐个串联展示，不出现汇总标签', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    const { container } = renderChat(port);
    await screen.findByLabelText('发送消息');

    // 3 个 = 实测「标题不截断」的上界（合计 199.45px，标题仍余 64.39px）。
    setActiveSkills(['daily-consulting', 'profile-curation', 'unknown-skill-c']);

    const tags = headTagTexts(container);
    expect(tags).toEqual(['日常咨询', '档案整理', 'unknown-skill-c']);
    expect(tags.some((tag) => tag.startsWith('技能 '))).toBe(false);
  });

  it('折叠态：4 个标签（实测标题开始被截断的那一档）整体折叠为「技能 4 个」，不出现任何单个技能名', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    const { container } = renderChat(port);
    await screen.findByLabelText('发送消息');

    setActiveSkills(['daily-consulting', 'profile-curation', 'unknown-skill-c', 'unknown-skill-d']);

    const tags = headTagTexts(container);
    expect(tags).toEqual(['技能 4 个']);
    // 授权语义明确否定「+N 徽标」形态：这里同时钉住它不是徽标写法。
    expect(tags[0]).not.toMatch(/^\+\d+$/);
  });

  it('OBS-01：页头技能标签显示中文名，不把 onboarding / emergency-consulting 标识符露给使用者', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    const { container } = renderChat(port);
    await screen.findByLabelText('发送消息');

    // 这两个是测试人员在页头上真实看到的原始名称（引导首轮 / 应急首轮）。
    setActiveSkills(['onboarding', 'emergency-consulting']);

    const tags = headTagTexts(container);
    expect(tags).toEqual(['一次性引导', '应急咨询']);
    // 不变量：页头上一个标识符形状的拉丁词都不能出现。
    for (const tag of tags) {
      expect(tag).not.toContain('onboarding');
      expect(tag).not.toContain('emergency-consulting');
    }
  });

  it('OBS-01：技能选择器的可选项里【没有】程序注入的两个技能（防可手选漏洞）', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    renderChat(port);
    await screen.findByLabelText('发送消息');

    // 选择器只渲染「自动」+ 目录里的可手选项（SkillPicker 遍历 store.skills）。
    const picker = screen.getByRole('group', { name: '下一条消息使用的技能' });
    const chips = Array.from(picker.querySelectorAll('.skill-chip')).map((el) => el.textContent ?? '');

    expect(chips).toEqual(['自动', '日常咨询', '档案整理']);
    // 这两个传入服务端即 422，因此不能出现在可手选入口里。
    expect(chips).not.toContain('onboarding');
    expect(chips).not.toContain('emergency-consulting');
    expect(chips).not.toContain('一次性引导');
    expect(chips).not.toContain('应急咨询');
  });
});

describe('对话页 — 设备外壳（宽视口）', () => {
  /**
   * 对话页是唯一不经 .phone-shell 的页面（消息满幅画布），因此它在外壳里的位置必须
   * 由结构钉住：三态都要落在 DeviceFrame 的屏幕区内，否则宽视口下会退回满幅网页。
   * jsdom 不算布局，这里只断言 DOM 归属——几何与可点性由浏览器探针覆盖。
   */
  it('P0 水合成功态装在设备外壳的屏幕区内（与其余 9 页一致）', async () => {
    const port = createConsultPortStub({
      history: historyResponse([hydratedAssistant('m1', [{ type: 'text', text: '历史回答' }])]),
    });
    const { container } = renderChat(port);
    await screen.findByLabelText('发送消息');

    const screenArea = container.querySelector('.device-screen');
    const workspace = container.querySelector('[class*="workspace"]');
    expect(screenArea).not.toBeNull();
    expect(workspace).not.toBeNull();
    expect(screenArea?.contains(workspace)).toBe(true);
  });

  it('P0 消息流与输入区同在外壳屏幕区内（滚动与贴底的前提）', async () => {
    const port = createConsultPortStub({
      history: historyResponse([hydratedAssistant('m1', [{ type: 'text', text: '历史回答' }])]),
    });
    const { container } = renderChat(port);
    await screen.findByLabelText('发送消息');

    const screenArea = container.querySelector('.device-screen');
    const thread = container.querySelector('[class*="thread"]');
    const composer = container.querySelector('.chat-compose');
    expect(thread).not.toBeNull();
    expect(composer).not.toBeNull();
    expect(screenArea?.contains(thread)).toBe(true);
    expect(screenArea?.contains(composer)).toBe(true);
  });

  it('P0 水合中与失败两态同样在外壳内（三态一致，不出现满幅态）', async () => {
    const loading = createConsultPortStub();
    vi.mocked(loading.loadHistory).mockReturnValue(pending<ListMessagesResponse>());
    const loadingView = renderChat(loading);
    expect(screen.getByText('正在载入这段对话…')).toBeDefined();
    expect(loadingView.container.querySelector('.device-screen')).not.toBeNull();
    loadingView.unmount();

    const failed = createConsultPortStub();
    vi.mocked(failed.loadHistory).mockRejectedValueOnce(new ConsultError('unavailable', '服务暂时不可用'));
    const failedView = renderChat(failed);
    await screen.findByRole('button', { name: '重试' });
    expect(failedView.container.querySelector('.device-screen')).not.toBeNull();
  });
});

describe('对话页 — 订阅不可续传后自动重读历史（2026-10-28 修复）', () => {
  it('流订阅不可续传（409/404）时重新读历史，把服务端已保存的回答显示出来', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    // 第一次水合是空会话；重新水合时服务端已经有了这一轮的回答（这正是真实情形：
    // 运行在服务端跑完了，只是客户端的订阅通道失效了）。
    vi.mocked(port.loadHistory)
      .mockResolvedValueOnce(historyResponse([]))
      .mockResolvedValue(
        historyResponse([
          hydratedAssistant('m1', [{ type: 'text', text: '这是服务端保存下来的回答' }]),
        ]),
      );
    port.failNextStream(new ConsultError('not-resumable', '运行元数据已不在（404）'));

    renderChat(port);
    await send('现场很吵，他捂住了耳朵');

    expect(await screen.findByText('这是服务端保存下来的回答')).toBeDefined();
    // 重读过一次：历史不再只有空会话那一次请求。
    expect(port.loadHistory).toHaveBeenCalledTimes(2);
  });
});

describe('对话页 — 运行中的输入区状态（演示装置依赖这条判据）', () => {
  /** 发送键；找不到时返回 null（待作答时输入区整体收起）。 */
  function sendButton(): HTMLButtonElement | null {
    return document.querySelector<HTMLButtonElement>('button[aria-label="发送"]');
  }

  it('运行中：有停止键、发送键禁用；停止后发送键恢复可用', async () => {
    const port = createConsultPortStub({ history: historyResponse([]) });
    // 「这一轮还没结束」是这条用例要观察的中间态：脚本吐完 run_started 与一段正文后挂着。
    port.holdStream([runStarted(['daily-consulting']), textDelta('他现在的状态比平时明显不同')]);

    renderChat(port);
    await send('现场很吵，他捂住了耳朵');

    // 运行中：正文已经出现，但本轮尚未结束。草稿里再写一句，让「禁用」只能是运行造成的
    // （发送键的另一条禁用理由是草稿为空，那条与运行无关）。
    expect(await screen.findByText('他现在的状态比平时明显不同')).toBeDefined();
    fireEvent.change(screen.getByLabelText('发送消息'), { target: { value: '补充一句' } });
    await waitFor(() => {
      expect(sendButton()?.disabled).toBe(true);
    });
    expect(screen.getByRole('button', { name: '停止' })).toBeDefined();

    // 停止 = 本地中断（契约 4.3：不发终态）。中断之后必须能继续输入，
    // 否则使用者会被卡在一个「永远正在生成」的界面里——演示装置正是拿这一点当结束判据。
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '停止' }));
    });
    await waitFor(() => {
      expect(sendButton()?.disabled).toBe(false);
    });
    expect(screen.queryByRole('button', { name: '停止' })).toBeNull();
  });
});
