/**
 * SSE 流模拟器 —— 使用 setTimeout 逐条发射 chunk 事件。
 * 接口兼容 SseStreamParser（connect + disconnect），供 consult store 在 mock 模式下使用。
 */
import type { SseStreamParserCallbacks } from '../../../consult/services/sseParser';
import type { ChunkEventPayload, DoneEventPayload } from '../../../consult/types';

interface MockSection {
  title: string;
  chunks: string[];
}

const CHUNK_MIN_DELAY_MS = 80;
const CHUNK_MAX_DELAY_MS = 200;
const DONE_DELAY_MS = 300;

function buildMockSections(): MockSection[] {
  return [
    {
      title: '即时安全干预动作',
      chunks: [
        '首先确保孩子处于安全环境中，移除周围可能造成伤害的物品。',
        '如果孩子在公共场所，建议暂时转移到安静、少刺激的角落。',
        '保持冷静的语气和缓慢的动作，避免突然的触碰或大声说话。',
      ],
    },
    {
      title: '情绪安抚话术',
      chunks: [
        '"妈妈/爸爸在这里陪着你，你现在是安全的。"',
        '"我们先深呼吸，跟我一起数到五，好吗？一、二、三、四、五——"',
        '"我知道你现在很难受，这种感觉会过去的，我们一起等它过去。"',
      ],
    },
    {
      title: '后续观察指标',
      chunks: [
        '记录本次行为发生的具体时间、地点和可能的触发因素。',
        '观察行为持续时间：通常此类行为持续 5-20 分钟，超过 30 分钟需特别关注。',
        '注意行为强度和频率的变化趋势，连续 3 天频率增加建议进行专业评估。',
      ],
    },
    {
      title: '就医判断标准',
      chunks: [
        '若行为伴随自伤或伤人风险，或持续时间超过 1 小时，建议尽快就医。',
        '若出现新的行为模式或现有行为明显恶化，建议预约发育行为儿科医生。',
        '定期随访：建议每 3-6 个月进行一次行为评估复诊。',
      ],
    },
  ];
}

export class MockSseSimulator {
  private callbacks: SseStreamParserCallbacks;
  private isActive: boolean = false;
  private timers: ReturnType<typeof setTimeout>[] = [];

  constructor(
    callbacks: SseStreamParserCallbacks,
    _behaviorDescription: string,
  ) {
    this.callbacks = callbacks;
  }

  async connect(_url: string, _headers?: Record<string, string>): Promise<void> {
    this.isActive = true;
    const sections = buildMockSections();

    let sequence = 0;
    for (const section of sections) {
      for (const chunk of section.chunks) {
        if (!this.isActive) return;
        sequence++;
        await this.sleep(CHUNK_MIN_DELAY_MS + Math.random() * (CHUNK_MAX_DELAY_MS - CHUNK_MIN_DELAY_MS));

        const payload: ChunkEventPayload = {
          text: chunk,
          sequence,
          section: section.title,
        };
        this.callbacks.onChunk?.(payload);
      }
    }

    if (!this.isActive) return;
    this.callbacks.onHeartbeat?.();

    await this.sleep(DONE_DELAY_MS);
    if (!this.isActive) return;

    const sectionsMap: Record<string, string[]> = {};
    for (const s of sections) {
      sectionsMap[s.title] = s.chunks;
    }

    const donePayload: DoneEventPayload = {
      finish_reason: 'COMPLETE',
      sequence,
      crisis_level: 'mild',
      referenced_slice_ids: ['mock-slice-001', 'mock-slice-002'],
      referenced_cases: [
        {
          slice_id: 'mock-slice-001',
          case_id: 'mock-case-001',
          case_title: '学龄前 ASD 儿童刻板行为干预案例',
          slice_text: '通过结构化环境调整和替代行为训练...',
        },
      ],
      confidence_score: 0.87,
      verdict: 'PASS',
      ticket_triggered: false,
      sections: sectionsMap,
    };
    this.callbacks.onDone?.(donePayload);
  }

  disconnect(): void {
    this.isActive = false;
    for (const t of this.timers) {
      clearTimeout(t);
    }
    this.timers = [];
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      const timer = setTimeout(resolve, ms);
      this.timers.push(timer);
    });
  }
}
