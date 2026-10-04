/**
 * 模块: features/consult/domain/emergency
 * 职责: 应急表单的八项题面、作答草稿与提交载荷（纯规则，无框架依赖）
 * 数据来源:
 *   - docs/design/pages/应急表单页.md: MUST — 布局结构（一屏一题、每题形态、可跳过、提交不需答完）
 *   - docs/技术设计/面/consult/skills/emergency-consulting.md: MUST — 第 2 节（八项）与第 3.2/3.4 节（取值与档位）
 *   - docs/技术设计/面/consult/HTTP与SSE契约.md: MUST — 第 5 节（items 载荷：key/values/value/skipped）
 * 边界:
 *   - 依赖: shared/types/consult（EmergencyItem）
 *   - 被依赖: viewModel 的 useEmergencyForm 与 view 的应急表单页
 * 禁止行为:
 *   - 禁止把未作答项当成正常值提交（未作答 = 未排除，必须以 skipped: true 表达）
 *   - 禁止为跳过项带上值（契约第 5 节：skipped 为真时不传任何值）
 *   - 禁止把跳过语义弱化成「暂时跳过」（页面设计第 43 行固定文案）
 */

import type { EmergencyItem } from '../../../shared/types/consult';

/** 控件形态：多项勾选 / 三选一 / 自由文本。 */
export type EmergencyControl = 'multi' | 'single' | 'text';

/** 一个选项：label 是题面文字，value 是传输标识。 */
export interface EmergencyOption {
  label: string;
  value: string;
}

/** 一道现场采集题。 */
export interface EmergencyQuestion {
  /** 传输标识（契约第 5 节的 key，不得改名）。 */
  key: string;
  prompt: string;
  hint: string;
  control: EmergencyControl;
  options: readonly EmergencyOption[];
  /** 是否允许附加自由补充（痛苦程度与感觉环境两项，页面设计第 18 行）。 */
  allowNote: boolean;
}

/**
 * 八项现场采集（契约第 5 节的 key 顺序）。
 *
 * 取值标识的出处：`baseline_deviation` / `communication` / `medical_risk` 的取值来自
 * emergency-consulting 第 3.2/3.4 节；`primary_risk` 的五个取值来自应急表单页设计第 18 行
 * （medical/self/others/elopement/environment）；`possible_pain` 的 `uncertain` 有契约第 5 节
 * 的示例为证。医疗红灯与感觉环境的标识符、痛苦程度的档位文字在设计文档里只有中文散文
 * 清单、没有标识符——这里按清单语义定名（见报告「未决问题」节，待与 skill 词表对表）。
 */
export const EMERGENCY_QUESTIONS: readonly EmergencyQuestion[] = [
  {
    key: 'medical_red_flags',
    prompt: '现在有没有以下医疗危险表现？',
    hint: '可以多选；不确定或无法核对时，直接跳过。',
    control: 'multi',
    allowNote: false,
    options: [
      { label: '意识改变', value: 'altered_consciousness' },
      { label: '呼吸异常', value: 'abnormal_breathing' },
      { label: '严重出血', value: 'severe_bleeding' },
      { label: '明显外伤', value: 'obvious_injury' },
      { label: '癫痫持续或异常发作', value: 'seizure' },
      { label: '中毒或误服', value: 'poisoning' },
      { label: '严重过敏', value: 'severe_allergy' },
      { label: '明显疼痛', value: 'obvious_pain' },
      { label: '突然出现与平时完全不同的表现', value: 'sudden_change' },
    ],
  },
  {
    key: 'baseline_deviation',
    prompt: '和平时相比，现在的变化有多大？',
    hint: '按这个人平时的样子判断，不是按「像不像典型表现」。',
    control: 'single',
    allowNote: false,
    // 三档呈现（页面设计第 18 行）对应五值枚举的四档取值折叠：无/轻度/明显。
    // 折叠后取档内首值（mild/severely_reduced）：档位显示与取值一一可查，不暗中升档或降档。
    options: [
      { label: '无', value: 'none' },
      { label: '轻度', value: 'mild' },
      { label: '明显', value: 'marked' },
    ],
  },
  {
    key: 'communication',
    prompt: '他现在还能怎样沟通？',
    hint: '选最接近的一项；不确定就跳过。',
    control: 'single',
    allowNote: false,
    options: [
      { label: '正常', value: 'baseline' },
      { label: '下降', value: 'reduced' },
      { label: '严重下降', value: 'severely_reduced' },
    ],
  },
  {
    key: 'distress',
    prompt: '他现在看起来有多难受？',
    hint: '可以补一句你观察到的样子。',
    control: 'single',
    allowNote: true,
    options: [
      { label: '轻微', value: 'mild' },
      { label: '中等', value: 'moderate' },
      { label: '强烈', value: 'severe' },
    ],
  },
  {
    key: 'sensory_environment',
    prompt: '现在的环境里有什么？',
    hint: '可以多选，也可以补一句。',
    control: 'multi',
    allowNote: true,
    options: [
      { label: '噪音', value: 'noise' },
      { label: '灯光', value: 'light' },
      { label: '人群', value: 'crowd' },
      { label: '温度', value: 'temperature' },
    ],
  },
  {
    key: 'what_happened',
    prompt: '刚刚发生了什么？',
    hint: '一两句话就够，写不清也可以跳过。',
    control: 'text',
    allowNote: false,
    options: [],
  },
  {
    key: 'primary_risk',
    prompt: '现在最大的风险是什么？',
    hint: '选一个最需要注意的方向。',
    control: 'single',
    allowNote: false,
    options: [
      { label: '医疗', value: 'medical' },
      { label: '自伤', value: 'self' },
      { label: '伤人', value: 'others' },
      { label: '走失', value: 'elopement' },
      { label: '环境', value: 'environment' },
    ],
  },
  {
    key: 'possible_pain',
    prompt: '有没有可能正在疼痛？',
    hint: '不确定也可以选「不确定」。',
    control: 'single',
    allowNote: false,
    options: [
      { label: '否', value: 'no' },
      { label: '不确定', value: 'uncertain' },
      { label: '是', value: 'yes' },
    ],
  },
];

/** 某题的作答草稿。 */
export interface EmergencyAnswerDraft {
  selected: readonly string[];
  note: string;
  skipped: boolean;
}

/** 整张表单的草稿（题 key → 草稿）。 */
export type EmergencyDraft = Readonly<Record<string, EmergencyAnswerDraft>>;

/** 跳过语义的固定文案（页面设计第 43 行；不得弱化为「暂时跳过」）。 */
export const SKIP_SEMANTICS_COPY = '跳过 = 未排除，不会当作正常';

/** 一个空草稿。 */
const EMPTY_ANSWER: EmergencyAnswerDraft = { selected: [], note: '', skipped: false };

/** 建一份空表单：八项全部未处理。 */
export function createEmergencyDraft(): EmergencyDraft {
  const draft: Record<string, EmergencyAnswerDraft> = {};
  for (const question of EMERGENCY_QUESTIONS) draft[question.key] = EMPTY_ANSWER;
  return draft;
}

/** 取某题草稿；未知 key 抛出（不得静默当成未作答）。 @throws Error 采集项 key 不在八项内 */
export function emergencyAnswerFor(draft: EmergencyDraft, key: string): EmergencyAnswerDraft {
  const answer = draft[key];
  if (answer === undefined) throw new Error(`应急采集项 ${key} 不在八项内`);
  return answer;
}

/** 该题是否会作为「已作答」提交（与 skipped 相对）。 */
function hasAnswer(answer: EmergencyAnswerDraft, question: EmergencyQuestion): boolean {
  if (question.control === 'text') return answer.note.trim() !== '';
  return answer.selected.length > 0 || answer.note.trim() !== '';
}

/** 写入某题草稿；作答会清除该题的跳过标记（答了就不算跳过）。 */
function withAnswer(
  draft: EmergencyDraft,
  key: string,
  answer: EmergencyAnswerDraft,
): EmergencyDraft {
  emergencyAnswerFor(draft, key);
  return { ...draft, [key]: answer };
}

/** 多项勾选：切换一项。 */
export function toggleOption(draft: EmergencyDraft, key: string, value: string): EmergencyDraft {
  const current = emergencyAnswerFor(draft, key);
  const selected = current.selected.includes(value)
    ? current.selected.filter((item) => item !== value)
    : [...current.selected, value];
  return withAnswer(draft, key, { ...current, selected, skipped: false });
}

/** 三选一：选中一项（再点同一项不取消——单选没有「无」这个第二通道，跳过是它）。 */
export function selectOption(draft: EmergencyDraft, key: string, value: string): EmergencyDraft {
  const current = emergencyAnswerFor(draft, key);
  return withAnswer(draft, key, { ...current, selected: [value], skipped: false });
}

/** 写入自由补充文本。 */
export function setNote(draft: EmergencyDraft, key: string, note: string): EmergencyDraft {
  const current = emergencyAnswerFor(draft, key);
  return withAnswer(draft, key, { ...current, note, skipped: false });
}

/** 跳过某题（清空该题作答，跳过与作答互斥）。 */
export function skipQuestion(draft: EmergencyDraft, key: string): EmergencyDraft {
  return withAnswer(draft, key, { selected: [], note: '', skipped: true });
}

/** 回到未处理（撤销跳过）。 */
export function resetQuestion(draft: EmergencyDraft, key: string): EmergencyDraft {
  return withAnswer(draft, key, EMPTY_ANSWER);
}

/** 该题是否已处理（作答或显式跳过）；用于进度条与题号显示。 */
export function isHandled(draft: EmergencyDraft, key: string): boolean {
  const answer = emergencyAnswerFor(draft, key);
  const question = EMERGENCY_QUESTIONS.find((item) => item.key === key);
  if (question === undefined) return false;
  return answer.skipped || hasAnswer(answer, question);
}

/**
 * 产出应急入口的 items 载荷。
 *
 * 前置: 无（八项全部可跳过，任意时刻都可提交）
 * 后置: 恒为八条、顺序与 EMERGENCY_QUESTIONS 一致；
 *       已作答项带 value/values，未作答与显式跳过项都是 `{skipped: true}` 且不带值
 * 异常: 不抛出
 *
 * 为什么未作答要写成 skipped: true 而不是空值：契约第 5 节要求 skipped 为真时不传值，
 * 而「跳过 = 未排除」的解释权在后端与 skill（技术设计第 6 节）。把未作答写成空值会让
 * 服务端把它读成「答了但为空」，那正是把未排除读成正常。
 */
export function toEmergencyItems(draft: EmergencyDraft): EmergencyItem[] {
  return EMERGENCY_QUESTIONS.map((question) => {
    const answer = emergencyAnswerFor(draft, question.key);
    if (answer.skipped || !hasAnswer(answer, question)) {
      return { key: question.key, skipped: true };
    }
    const note = answer.note.trim();
    if (question.control === 'text') {
      return { key: question.key, value: note, skipped: false };
    }
    if (question.control === 'single') {
      const value = answer.selected[0];
      if (value === undefined) return { key: question.key, skipped: true };
      return { key: question.key, value, skipped: false };
    }
    // 多项勾选：标识符在前，自由补充作为额外一项附在末尾（契约只有 values 一个数组位）。
    return {
      key: question.key,
      values: note === '' ? [...answer.selected] : [...answer.selected, note],
      skipped: false,
    };
  });
}

/** 校验一份 items 载荷符合契约第 5 节（key 是八项、跳过不带值、非跳过必须带值）。 @throws Error 项数不为八、key 越界、跳过带值或非跳过无值 */
export function validateEmergencyItems(items: readonly EmergencyItem[]): void {
  if (items.length !== EMERGENCY_QUESTIONS.length) {
    throw new Error(`应急采集须提交八项，实际 ${items.length} 项`);
  }
  const known = new Set(EMERGENCY_QUESTIONS.map((question) => question.key));
  for (const item of items) {
    if (!known.has(item.key)) throw new Error(`应急采集项 ${item.key} 不在八项内`);
    if (item.skipped) {
      if (item.value !== undefined || item.values !== undefined) {
        throw new Error(`应急采集项 ${item.key} 标为跳过却带了值`);
      }
      continue;
    }
    const hasValue = (item.value ?? '') !== '' || (item.values !== undefined && item.values.length > 0);
    if (!hasValue) throw new Error(`应急采集项 ${item.key} 没有标为跳过却没有值`);
  }
}
