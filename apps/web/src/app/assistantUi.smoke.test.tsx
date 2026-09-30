/**
 * 模块: src/app/assistantUi.smoke.test
 * 职责: assistant-ui 落地复核——LocalRuntime 装配、data-* part 渲染与所需原语是否存在
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 2 节（runtime 选型）、
 *     第 5 节（citation 作为 data-* 自定义 part）
 *   - apps/web/README.md: MUST — assistant-ui 的 data-* part 等 API「未在本地跑过，落地前以实际版本复核」
 * 边界:
 *   - 依赖: @assistant-ui/react（版本锁定在 package.json）
 *   - 被依赖: 无（本包不做对话页实现，T11 才建 adapter）
 * 禁止行为:
 *   - 禁止用「文档说存在」替代实测（本文件就是那次实测的留档）
 *   - 禁止在本用例里调后端（只验库 API，不验契约）
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  AssistantRuntimeProvider,
  MessagePrimitive,
  ThreadPrimitive,
  useLocalRuntime,
  type ChatModelAdapter,
  type ThreadMessageLike,
} from '@assistant-ui/react';

/** 最小 adapter：本用例不发起任何运行，只验证类型与 runtime 能被构造。 */
const adapter: ChatModelAdapter = {
  async run() {
    return { content: [{ type: 'text', text: '' }] };
  },
};

/** citation part 的自定义渲染器——用来证明 data-* part 真的路由到了我们的组件。 */
function CitationProbe() {
  return <p>引用渲染器已接通</p>;
}

/** 文本 part 渲染器；定义在组件外，避免每次渲染都产生新的组件类型。 */
function TextProbe({ text }: { text: string }) {
  return <p>{text}</p>;
}

/**
 * part 渲染配置。
 *
 * 要点：by_name 的键是去掉 data- 前缀后的名字——库在 thread-message-like.ts 里执行
 * `type.substring(5)`，因此消息 part 写 data-citation，注册与分派用的名字是 citation。
 * 这一点是本包对 apps/web/README.md「data-* part 未在本地跑过」的实测结论。
 */
const PART_COMPONENTS = {
  Text: TextProbe,
  data: { by_name: { citation: CitationProbe } },
} as const;

/** 一条带自定义 data part 的 assistant 消息。 */
const initialMessages: readonly ThreadMessageLike[] = [
  {
    id: 'm1',
    role: 'assistant',
    content: [
      { type: 'text', text: '这是历史回答' },
      { type: 'data-citation', data: { citation_id: 'c1', source: 's', reference: 'r' } },
    ],
  },
];

/** 最小 Thread：Root + Viewport + Messages + Message.Parts，与咨询对话界面第 2 节的路径一致。 */
function SmokeThread() {
  const runtime = useLocalRuntime(adapter, { initialMessages });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root>
        <ThreadPrimitive.Viewport>
          <ThreadPrimitive.Messages>
            {() => (
              <MessagePrimitive.Root>
                <MessagePrimitive.Parts components={PART_COMPONENTS} />
              </MessagePrimitive.Root>
            )}
          </ThreadPrimitive.Messages>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}

describe('assistant-ui 冒烟', () => {
  it('LocalRuntime + ChatModelAdapter 可用，Thread 能渲染出消息', async () => {
    render(<SmokeThread />);

    expect(await screen.findByText('这是历史回答')).toBeDefined();
  });

  it('data-* part 路由到自定义渲染器', async () => {
    render(<SmokeThread />);

    // 这条断言是本包对 README「data-* part 未在本地跑过」的复核结论：
    // 渲染器被真正调用，说明 data-citation 走的是 data part 通道而不是被丢弃。
    expect(await screen.findByText('引用渲染器已接通')).toBeDefined();
  });

  it('所需原语在同一版本上存在', () => {
    expect(typeof useLocalRuntime).toBe('function');
    expect(typeof ThreadPrimitive.Root).not.toBe('undefined');
    expect(typeof ThreadPrimitive.Viewport).not.toBe('undefined');
    expect(typeof ThreadPrimitive.Messages).not.toBe('undefined');
    expect(typeof MessagePrimitive.Root).not.toBe('undefined');
    expect(typeof MessagePrimitive.Parts).not.toBe('undefined');
  });
});
