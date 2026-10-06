/**
 * 模块: features/consult/application/usecases 的幂等键生成
 * 职责: 守住「明文 HTTP 下也能生成幂等键」这条被线上暴露出来的性质
 * 数据来源:
 *   - docs/技术设计/面/咨询.md: MUST — 第 2 节（幂等键）
 * 边界:
 *   - 依赖: vitest
 *   - 被依赖: 无（纯测试）
 * 禁止行为:
 *   - 禁止只测「能生成一个字符串」而不测非安全上下文——那正是本文件存在的理由
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { SendMessageUseCase, newClientMessageId } from './usecases';
import { createConsultPortStub } from '../test/consultPortStub';

/**
 * 为什么这个用例必须存在（2026-10-01 真机缺陷的回归防线）：
 *
 * `crypto.randomUUID` 是 secure context 专有 API。线上走明文 HTTP 时它是
 * `undefined`，于是 `newClientMessageId()` 抛
 * `TypeError: crypto.randomUUID is not a function`——而它发生在发请求之前，
 * 所以服务端日志与网络面板里都看不到任何请求，界面上只有一条笼统的
 * 「出现了未预期的错误」。
 *
 * 原来抓不到它的原因是：所有调用方（chatAdapter）在测试里都注入了固定的
 * `newId: () => 'fixed-id'`，于是真实实现从未被跑到。本文件直接测真实实现，
 * 并且显式把环境改成非安全上下文——这是对线上情形的等价复现。
 */

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('newClientMessageId', () => {
  const originalCrypto = globalThis.crypto;

  afterEach(() => {
    Object.defineProperty(globalThis, 'crypto', { value: originalCrypto, configurable: true });
    vi.restoreAllMocks();
  });

  it('安全上下文下优先用 crypto.randomUUID', () => {
    const randomUUID = vi.fn(() => '11111111-2222-4333-8444-555555555555');
    Object.defineProperty(globalThis, 'crypto', {
      value: { randomUUID, getRandomValues: originalCrypto.getRandomValues.bind(originalCrypto) },
      configurable: true,
    });

    expect(newClientMessageId()).toBe('11111111-2222-4333-8444-555555555555');
    expect(randomUUID).toHaveBeenCalledTimes(1);
  });

  it('非安全上下文（randomUUID 缺失）不抛错，并回落到 getRandomValues', () => {
    // 等价复现线上明文 HTTP：crypto 存在、getRandomValues 可用，但 randomUUID 不是函数。
    Object.defineProperty(globalThis, 'crypto', {
      value: { getRandomValues: originalCrypto.getRandomValues.bind(originalCrypto) },
      configurable: true,
    });

    const id = newClientMessageId();

    expect(id).toMatch(UUID_V4);
  });

  it('回落路径生成的仍是合法 UUIDv4 且互不相同', () => {
    Object.defineProperty(globalThis, 'crypto', {
      value: { getRandomValues: originalCrypto.getRandomValues.bind(originalCrypto) },
      configurable: true,
    });

    const ids = new Set(Array.from({ length: 64 }, () => newClientMessageId()));

    expect(ids.size).toBe(64);
    for (const id of ids) expect(id).toMatch(UUID_V4);
  });

  it('回落路径保留版本号与变体位（不是随便拼的十六进制）', () => {
    Object.defineProperty(globalThis, 'crypto', {
      value: { getRandomValues: originalCrypto.getRandomValues.bind(originalCrypto) },
      configurable: true,
    });

    for (let i = 0; i < 32; i += 1) {
      const id = newClientMessageId();
      // 第 3 组的首位固定为 4；第 4 组首位只能是 8/9/a/b。
      expect(id[14]).toBe('4');
      expect('89ab').toContain(id[19]);
    }
  });
});

/**
 * 序列化边界（T43 交付物的验收点）：内部名 `batchId` → 出网键名 `batch_id`。
 *
 * 这里断言的是实际会被 `fetch` 序列化出去的那份对象（`sendMessage` 收到的 payload），
 * 而不是「某个函数被调用了」——后者正是本包最可能出假绿的形态。
 */
describe('SendMessageUseCase — 作答载荷的 batch_id 映射', () => {
  /** 建一个只关心 sendMessage 的端口替身。 */
  async function sendWith(submission?: { batchId: string; answers: { id: string; value?: string }[] }) {
    const port = createConsultPortStub();
    const useCase = new SendMessageUseCase(port);
    await useCase.execute({
      sessionId: 's1',
      ...(submission === undefined ? {} : { submission }),
      newId: () => 'fixed-id',
    });
    const payload = port.sendCalls[0]?.payload;
    if (payload === undefined) throw new Error('sendMessage 未被调用');
    return payload;
  }

  it('★ 出网键名逐字是 batch_id（snake_case），值等于提交件里的 batchId', async () => {
    const payload = await sendWith({ batchId: 'b-42', answers: [{ id: 'q1', value: '可以' }] });

    expect(payload).toEqual({
      answers: [{ id: 'q1', value: '可以' }],
      batch_id: 'b-42',
      skill: null,
      client_message_id: 'fixed-id',
    });
    // 实际字节：JSON 文本里出现的必须是 batch_id，且不得出现内部名 batchId。
    const wire = JSON.stringify(payload);
    expect(wire).toContain('"batch_id":"b-42"');
    expect(wire).not.toContain('batchId');
  });

  it('★ batchId 缺失时不阻断提交：载荷里没有 batch_id 这个键（不是 undefined、不是空串）', async () => {
    const payload = await sendWith({ batchId: '', answers: [{ id: 'q1', value: '可以' }] });

    expect(payload).toEqual({
      answers: [{ id: 'q1', value: '可以' }],
      skill: null,
      client_message_id: 'fixed-id',
    });
    expect('batch_id' in payload).toBe(false);
    // 与「显式 undefined」区分开：那会让键存在（`'batch_id' in payload === true`）。
    expect(payload).not.toHaveProperty('batch_id');
  });

  it('普通消息形态不带 batch_id（该字段只属于作答形态）', async () => {
    const port = createConsultPortStub();
    await new SendMessageUseCase(port).execute({ sessionId: 's1', content: '你好', newId: () => 'fixed-id' });

    const payload = port.sendCalls[0]?.payload ?? {};
    expect(payload).toEqual({ content: '你好', skill: null, client_message_id: 'fixed-id' });
    expect('batch_id' in payload).toBe(false);
  });

  it('★ 两组不同值：值来自传入的那一个提交件（不是模块级/闭包里的旧值）', async () => {
    const first = await sendWith({ batchId: 'b1', answers: [{ id: 'q1', value: '可以' }] });
    const second = await sendWith({ batchId: 'b2', answers: [{ id: 'q1', value: '不确定' }] });

    expect((first as { batch_id?: string }).batch_id).toBe('b1');
    expect((second as { batch_id?: string }).batch_id).toBe('b2');
  });
});
