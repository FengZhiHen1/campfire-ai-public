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
function renderChat(port: ConsultPortStub) {
  return render(
    <MemoryRouter initialEntries={['/consult/sessions/s1']}>
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

  it('历史里的提问是静态记录（不接受再次作答）', async () => {
    const port = createConsultPortStub({
      history: historyResponse([
        hydratedAssistant('m1', [{ type: 'question', batch_id: 'b1', items: [...QUESTION_ITEMS] }]),
      ]),
    });
    renderChat(port);

    expect(await screen.findByText('这组问题已经处理过，记录如下（回答见当时的对话）。')).toBeDefined();
    expect(screen.queryByRole('button', { name: '提交' })).toBeNull();
  });
});

describe('对话页 — 依据区（citation）', () => {
  it('默认收起；展开后含标题与来源（当前线格式没有可跳转的条目标识）', async () => {
    const port = createConsultPortStub({
      history: historyResponse([
        hydratedAssistant('m1', [{ type: 'text', text: '历史回答' }, { type: 'citation', citation: citation() }]),
      ]),
    });
    renderChat(port);

    const summary = await screen.findByText('依据 1 条');
    const details = summary.closest('details');
    expect(details?.hasAttribute('open')).toBe(false);
    expect(screen.getByText('沟通方式记录（虚构样例）')).toBeDefined();
    expect(document.querySelector('.citation-item .meta')?.textContent).toContain('来源：项目内虚构资料');
    expect(document.querySelector('.citation-item .meta')?.textContent).toContain('暂不能跳转');

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
      skill: null,
      client_message_id: expect.any(String),
    });

    // 提交后成为静态已提交记录，输入区恢复。
    expect(await screen.findByText('整组已提交，不能再修改。')).toBeDefined();
    expect(screen.queryByRole('button', { name: '提交' })).toBeNull();
    expect(await screen.findByLabelText('发送消息')).toBeDefined();
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
    expect(row.textContent).toContain('search_knowledge · 已结束');
    expect(row.textContent).toContain('找到 2 条');
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

    expect(await screen.findByText('检索或档案暂时不可用')).toBeDefined();
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
    port.script([runStarted(['emergency-consulting']), textDelta('好的'), runFinished()]);
    renderChat(port);
    await screen.findByLabelText('发送消息');

    fireEvent.click(screen.getByRole('button', { name: '应急咨询' }));
    expect(screen.getByRole('button', { name: '应急咨询' }).getAttribute('aria-pressed')).toBe('true');

    await send('他突然捂住耳朵');

    await waitFor(() => expect(port.sendCalls).toHaveLength(1));
    expect(port.sendCalls[0]?.payload).toMatchObject({ skill: 'emergency-consulting' });
    await waitFor(() => expect(useRunStore.getState().peekPendingSkill()).toBeNull());
    expect(screen.getByRole('button', { name: '自动' }).getAttribute('aria-pressed')).toBe('true');
  });
});
