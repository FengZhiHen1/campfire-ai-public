/**
 * 模块: features/consult/domain/actionCard
 * 职责: 行动卡的纯转换内核——通用信封 → 可渲染视图（七节分派、状态词表、来源标注定位）
 * 数据来源:
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6.2 节（七节分派、越界值拒渲染、旧卡失效）
 *   - docs/技术设计/面/consult/tools/emit_emergency_action_card.md: MUST — 第 2、4 节（七节 key 与状态词表）
 *   - docs/技术设计/面/consult/skills/emergency-consulting.md: MUST — 第 3.4 节（三档映射、来源六类、置信四档）
 *   - docs/design/pages/对话页.md: MUST — 契约修订 4（徽章三值、来源/置信文字标签、失效态）
 * 边界:
 *   - 依赖: shared/types/sse（ActionCard* 线格式）、features/consult/domain/types
 *   - 被依赖: view 层的 ActionCard 渲染器
 * 禁止行为:
 *   - 禁止解析模型正文猜卡片结构（卡片只信事件载荷，技术设计第 6.2 节）
 *   - 禁止把越界状态取值静默替换成合法值（emit 契约第 5 节「不静默改写」）
 *   - 禁止把 unknown/缺失读成「无变化」（emit 契约第 4 节：按未排除处理）
 *   - 禁止把定位不到的标注指到别的行（编排器裁决 A9：不渲染该标注）
 */

import type { ActionCardEvent, ActionCardSection, ActionCardState } from '../../../shared/types/sse';

/**
 * 七节的规范顺序（工具契约第 2 节）。
 *
 * 后端产出的七节恒为此顺序（emit 工具按 SECTION_KEYS 规范化）；前端按同一顺序渲染，
 * 因此「按七节顺序把各行摊平」的 1 起序号在两端一致。若载荷里出现契约外的 key，
 * 追加在末尾而不是丢弃——多出来的节被显示出来比被悄悄吞掉安全。
 */
export const SECTION_ORDER: readonly string[] = [
  'status',
  'communicate',
  'do_now',
  'avoid',
  'medical_checks',
  'safety',
  'when_to_escalate',
];

/** 需要突出为「现在先看」的节：立即做。 */
const PRIORITY_SECTION_KEY = 'do_now';

/** 当前状态所在节：四个状态字段挂在这一节里。 */
const STATUS_SECTION_KEY = 'status';

/** 状态字段的取值 → 中文档位（工具契约第 4 节的映射表；unknown 归入「未排除」）。 */
const STATE_VALUE_LABELS: Readonly<Record<string, Readonly<Record<string, string>>>> = {
  deviation: {
    none: '无变化',
    mild: '轻度',
    moderate: '轻度',
    marked: '明显',
    unknown: '未排除',
  },
  // communication 与 sensory_load 的枚举表里没有 unknown，但工具契约第 4 节的正文明确
  // 「deviation、communication、sensory_load 取 unknown（或缺失）时按未排除处理」——
  // 因此把 unknown 收进词表（呈现为未排除），而不是当成越界载荷把整张卡拒掉。
  communication: {
    baseline: '正常',
    reduced: '下降',
    severely_reduced: '严重下降',
    unavailable: '严重下降',
    unknown: '未排除',
  },
  sensory_load: { low: '低', moderate: '中', high: '高', extreme: '高', unknown: '未排除' },
  medical_risk: { stable: '稳定', uncertain: '未排除', high_risk: '高风险' },
};

/** 状态字段在「当前状态」节里的行前缀。 */
const STATE_LINE_PREFIX: Readonly<Record<string, string>> = {
  deviation: '与平时相比',
  communication: '当前沟通',
  sensory_load: '当前感觉负荷',
};

/** 医疗风险三值 → 徽章。（DESIGN.md 反模式：不得用裸色块表达，必须走 .status 语义徽章。） */
const MEDICAL_RISK_TONES: Readonly<Record<string, 'stable' | 'unruled' | 'high'>> = {
  stable: 'stable',
  uncertain: 'unruled',
  high_risk: 'high',
};

/** 来源六类 → 显示名（技能设计第 3.4 节）。 */
const SOURCE_LABELS: Readonly<Record<string, string>> = {
  self_report: '本人报告',
  family_report: '家属报告',
  onsite_observation: '现场观察',
  history: '历史记录',
  medical_record: '医疗记录',
  ai_inference: 'AI 推断',
};

/** 置信四档 → 显示名（对话页设计第 45 行的四档文字标签）。 */
const CONFIDENCE_LABELS: Readonly<Record<string, string>> = {
  confirmed: '有据',
  likely: '较可能',
  possible: '可能',
  unknown: '未知',
};

/** 一条动作的来源与置信标注（已解码为显示名）。 */
export interface SourceAnnotation {
  source: string;
  sourceLabel: string;
  confidence: string;
  confidenceLabel: string;
}

/** 一行动作及其标注。 */
export interface ActionCardLineView {
  text: string;
  /** null = 该行没有可用的来源标注（载荷未给，或标注定位不到该行而被丢弃）。 */
  annotation: SourceAnnotation | null;
}

/** 一个分节的渲染数据。 */
export interface ActionCardSectionView {
  key: string;
  heading: string;
  /** 显示序号（01 起，按渲染顺序）。 */
  ordinal: string;
  isPriority: boolean;
  lines: ActionCardLineView[];
}

/** 医疗风险徽章。 */
export interface MedicalRiskBadge {
  tone: 'stable' | 'unruled' | 'high';
  /** 徽章内文字，如「医疗风险 · 未排除」。 */
  text: string;
}

/** 行动卡的渲染视图。 */
export interface ActionCardView {
  cardId: string;
  title: string;
  sections: ActionCardSectionView[];
  medicalRisk: MedicalRiskBadge;
  /**
   * 医疗风险徽章应插在哪个节的首行；null = 载荷里没有「当前状态」节，徽章渲染在卡首。
   * 徽章位置由契约（components.html 把 .status 三值徽章放在 01 当前状态节内）决定。
   */
  medicalRiskSectionKey: string | null;
  /** 其余状态字段的读出行（与平时相比 / 当前沟通 / 当前感觉负荷）。 */
  stateLines: string[];
  /** 失效态（重复评估后的旧卡）。 */
  expired: boolean;
  /** 被丢弃的标注条数（定位不到行或取值越界）；供测试与诊断。 */
  droppedAnnotations: number;
}

/** 构建结果：要么可渲染，要么被拒（越界载荷不得渲染出「看起来合法」的卡）。 */
export type ActionCardBuild =
  | { status: 'rendered'; view: ActionCardView }
  | { status: 'rejected'; reason: string };

/** 扁平化后的一行：所属节 + 节内行号。 */
interface FlatLine {
  sectionKey: string;
  lineIndex: number;
}

/**
 * 按七节规范顺序摊平各行，编号从 1 起。
 *
 * 为什么按规范顺序而不是载荷顺序：`line_ref` 的语义就是「按七节顺序摊平后的序号」，
 * 后端也按规范顺序产出；若载荷顺序乱序，后端不会重编号，此时按规范顺序摊平是本实现
 * 能给出的最好解释，指不到行的标注一律丢弃（不静默改指别的行）。
 */
function flattenLines(sections: readonly ActionCardSectionView[]): FlatLine[] {
  const flat: FlatLine[] = [];
  for (const section of sections) {
    for (let lineIndex = 0; lineIndex < section.lines.length; lineIndex += 1) {
      flat.push({ sectionKey: section.key, lineIndex });
    }
  }
  return flat;
}

/** 解码 kind = "{source}:{confidence}"；任一取值不在词表内返回 null。 */
function decodeAnnotation(kind: string): SourceAnnotation | null {
  const separator = kind.indexOf(':');
  if (separator <= 0) return null;
  const source = kind.slice(0, separator);
  const confidence = kind.slice(separator + 1);
  const sourceLabel = SOURCE_LABELS[source];
  const confidenceLabel = CONFIDENCE_LABELS[confidence];
  if (sourceLabel === undefined || confidenceLabel === undefined) return null;
  return { source, sourceLabel, confidence, confidenceLabel };
}

/** 状态字段 → 显示档位；未定义的键或取值返回 null（由调用方决定丢弃还是拒渲染）。 */
function stateLabel(key: string, value: string): string | null {
  return STATE_VALUE_LABELS[key]?.[value] ?? null;
}

/** 校验状态字段：返回被拒原因（null = 通过）。 */
function rejectReasonForStates(states: readonly ActionCardState[]): string | null {
  for (const state of states) {
    const vocabulary = STATE_VALUE_LABELS[state.key];
    // 契约外的状态键：不是越界（保留前向兼容），由渲染侧忽略。
    if (vocabulary === undefined) continue;
    if (vocabulary[state.value] === undefined) {
      return `状态字段 ${state.key} 取值越界：${state.value}`;
    }
  }
  return null;
}

/**
 * 把 action_card 事件转成渲染视图。
 *
 * 前置: event 是契约形状的 action_card 载荷（sections/states/annotations）
 * 后置: 返回可渲染视图；`states` 取值越界或 `sections` 为空时返回 rejected
 * 异常: 不抛出——载荷问题以 rejected 表达，由渲染侧改为错误呈现
 *
 * @param event 事件载荷
 * @param options.expired 是否为失效卡（同会话内已有更新的卡）
 */
export function buildActionCard(event: ActionCardEvent, options: { expired: boolean }): ActionCardBuild {
  if (!Array.isArray(event.sections) || event.sections.length === 0) {
    return { status: 'rejected', reason: '行动卡没有任何分节' };
  }

  const rejected = rejectReasonForStates(event.states);
  if (rejected !== null) return { status: 'rejected', reason: rejected };

  // 分节排序：规范 key 按 SECTION_ORDER，契约外 key 追加在末尾（保持载荷内相对顺序）。
  const known = SECTION_ORDER.map((key) => event.sections.find((section) => section.key === key)).filter(
    (section): section is ActionCardSection => section !== undefined,
  );
  const unknown = event.sections.filter((section) => !SECTION_ORDER.includes(section.key));

  const sections: ActionCardSectionView[] = [...known, ...unknown].map((section, index) => ({
    key: section.key,
    heading: section.heading,
    ordinal: String(index + 1).padStart(2, '0'),
    isPriority: section.key === PRIORITY_SECTION_KEY,
    lines: section.lines.map((text) => ({ text, annotation: null })),
  }));

  // 标注定位：target 是「按七节顺序摊平后的 1 起序号」，kind 是 "{source}:{confidence}"。
  const flat = flattenLines(sections);
  let droppedAnnotations = 0;
  for (const annotation of event.annotations) {
    const targetText = annotation.target.trim();
    const decoded = decodeAnnotation(annotation.kind);
    const position = /^\d+$/.test(targetText) ? flat[Number.parseInt(targetText, 10) - 1] : undefined;
    const section = position === undefined ? undefined : sections.find((item) => item.key === position.sectionKey);
    const line = position === undefined ? undefined : section?.lines[position.lineIndex];
    if (decoded === null || line === undefined) {
      // 指不到行或取值越界：丢弃这条标注，不改指别的行（编排器裁决 A9）。
      droppedAnnotations += 1;
      continue;
    }
    if (line.annotation === null) line.annotation = decoded;
  }

  const stateLines: string[] = [];
  let medicalRisk: MedicalRiskBadge = { tone: 'unruled', text: '医疗风险 · 未排除' };
  for (const state of event.states) {
    const label = stateLabel(state.key, state.value);
    if (label === null) continue;
    if (state.key === 'medical_risk') {
      const tone = MEDICAL_RISK_TONES[state.value];
      if (tone !== undefined) medicalRisk = { tone, text: `医疗风险 · ${label}` };
      continue;
    }
    const prefix = STATE_LINE_PREFIX[state.key];
    if (prefix !== undefined) stateLines.push(`${prefix}：${label}`);
  }

  // 医疗风险字段缺失/不可读时按「未排除」呈现（与跳过语义同源：不得读作稳定）。
  // 徽章由渲染侧插在「当前状态」节首（或全卡首），不在这里往 lines 里塞合成行——
  // 合成行会让「按七节摊平的序号」与载荷的行数错位。
  return {
    status: 'rendered',
    view: {
      cardId: event.card_id,
      title: event.title,
      sections,
      medicalRisk,
      medicalRiskSectionKey: sections.some((section) => section.key === STATUS_SECTION_KEY)
        ? STATUS_SECTION_KEY
        : null,
      stateLines,
      expired: options.expired,
      droppedAnnotations,
    },
  };
}
