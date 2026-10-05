/**
 * 模块: features/consult/domain/skills
 * 职责: 技能选择器可选项的目录（技能标识 ↔ 中文显示名）与技能名映射
 * 数据来源:
 *   - docs/技术设计/面/consult/skills/{daily-consulting,profile-curation}.md: MUST — 可手选的两个技能标识
 *   - docs/技术设计/decisions/激活记录即授权真源.md: MUST — `skill` 参数值域 = 模型可见目录集（2026-10-01 裁决）
 *   - docs/design/components.html: MUST — 对话工作面预览的技能 chip 文案（自动/日常咨询/档案整理）
 * 边界:
 *   - 依赖: features/consult/domain/types（SkillSummary）
 *   - 被依赖: viewModel 与端口实现
 * 禁止行为:
 *   - 禁止把 onboarding 放进可选项（它只由服务端程序注入，技能设计第 4 节）
 *   - 禁止把 emergency-consulting 放进可选项（应急只走表单入口，`skill` 参数传它回 422）
 *   - 禁止在此发明第四个技能（技能清单的权威在服务端 skill 目录，未知标识不猜测）
 *
 * 为什么目录在本层而不是从端点取：HTTP/SSE 契约第 3～6 节定义了会话、发消息、订阅、
 * 应急与引导跳过五组端点，没有技能目录端点；而技能选择器（RQ-CON-08）必须能列出
 * 可选项。这里按已确认的可手选技能标识与页面设计的中文名构成目录，作为目录端点的替身点，
 * 已在交付报告「未决问题」节登记（端点落地后此处改为远端读取，选择器无需改动）。
 */

import type { SkillSummary } from './types';

/** 应急技能标识；用于「首字超 10 秒」的降级提示判定（run_started.activated_skills 含它即应急运行）。 */
export const EMERGENCY_SKILL_ID = 'emergency-consulting';

/** 日常技能标识；"自动"之外最常用的选择，列表页「开始新的日常咨询」不预选（缺省即自动）。 */
export const DAILY_SKILL_ID = 'daily-consulting';

/** 档案整理技能标识。 */
export const CURATION_SKILL_ID = 'profile-curation';

/**
 * 可手选技能目录（顺序即 chip 顺序）。
 *
 * 只含模型可见目录集（daily-consulting、profile-curation）：`skill` 参数的合法值域
 * 与它一致，传值域外的名字服务端回 422。应急芯片已随值域裁决下架——应急只走表单入口。
 *
 * ⚠ **本表是【可选项】清单，不只是显示名表**：它经
 * `infrastructure/consult/consultPort.ts` 的 `listSkills()` 流向 `SkillPicker`，
 * 每一项都会渲染成一个**可点选**的 chip（`SkillPicker.tsx` 遍历本表）。
 * 因此**不得**把程序注入的两个技能（`onboarding` / `emergency-consulting`）加进来——
 * 那会让它们变成可手选，直接违反下方「禁止行为」两行。
 * 这两个的**显示名**走 `INJECTED_SKILL_LABELS`（见下），两张表刻意分开。
 */
export const SKILL_CATALOG: readonly SkillSummary[] = [
  { id: DAILY_SKILL_ID, label: '日常咨询' },
  { id: CURATION_SKILL_ID, label: '档案整理' },
];

/**
 * 程序注入技能的显示名（**不是可选项**，故与 `SKILL_CATALOG` 分开）。
 *
 * ★ 为什么单独一张表、而不是往 `SKILL_CATALOG` 里加两行：
 * `SKILL_CATALOG` 的消费者不只是「取显示名」——它还经 `listSkills()` 变成
 * `SkillPicker` 的可点选 chip。把这两个加进去就等于**把它们变成可手选技能**，
 * 而这是明令禁止的：`onboarding` 只由服务端按引导状态表程序注入（手选等于绕过触发
 * 条件），`emergency-consulting` 只走应急表单入口（传它回 422）。
 * 两张表的名字如此接近，后来者很可能"顺手合并"——**那会重新引入可手选漏洞**，
 * 因此这里写死这条边界。防回归由 `skills.test.ts` 的用例机械守住
 * （把映射错放进 `SKILL_CATALOG` ⇒ 用例必红）。
 *
 * ★ 显示名的出处（**两个都不是在面层发明**；本项目禁止静默发明术语）：
 * - `emergency-consulting` → 「应急咨询」：**视觉契约正本** `docs/design/components.html`
 *   的 `chatSkillNames`（该文件第 1225 行：`emergency: '应急咨询'`），且它正是用在
 *   「当前生效技能」这个位置上（同文件用它写 `.sp-tag` 的文案）。目录表里
 *   `daily` → 「日常咨询」、`profile` → 「档案整理」与本表既有两行逐字一致，
 *   可见该对象就是同一个映射的真源，`emergency` 这一项因此可直接取用、无需造词。
 * - `onboarding` → 「一次性引导」：取自**技能设计正本**
 *   `docs/技术设计/technical-details/技能设计.md` 第 1 节总表对该 skill 的定义
 *   （「账号首次日常会话的**一次性引导**」），决策记录
 *   `docs/技术设计/decisions/一次性引导对话.md` 同名同词。
 *   ⚠ **如实登记**：`docs/design/` 页面设计里**没有**给 `onboarding` 规定显示名
 *   （`docs/design/pages/对话页.md` 只要求页头展示「当前生效技能」，未命名），
 *   `components.html` 的 `chatSkillNames` 也**不含** onboarding——它是四个**可手选**
 *   场景的名称表，而 onboarding 本就不可手选。因此这个名字是**从技术设计文档的既有
 *   中文术语引用而来**，不是此处新造；但它是**本包首次把它用于界面文案**，
 *   故登记为待确认项（见交付报告「证据边界」）。
 *
 * 取值取舍：「一次性引导」比「初次建档」更准——该 skill 的职责是告知数据用途、
 * 创建第一个支持对象、播下档案种子、了解照护经验并指引使用说明页（技能设计第 1 节），
 * 「建档」只覆盖其中一项，用作标签会把一段五步流程说成一次建档。
 */
export const INJECTED_SKILL_LABELS: Readonly<Record<string, string>> = {
  'emergency-consulting': '应急咨询',
  onboarding: '一次性引导',
};

/**
 * 按标识取显示名。
 *
 * 先查可手选目录，再查程序注入技能的名称表；两者都未命中时**返回标识符本身**
 * （不猜测、不隐藏）——这个兜底是刻意的 fail-open：服务端可能新增技能，
 * 前端不该瞎编一个中文名冒充权威术语，显示原文名至少是诚实的。
 * 因此这里**不改成「一律中性兜底」**：那会把「未知技能暴露了标识符」这个
 * 可诊断的信号，变成「一个看不出问题的通用词」。
 *
 * 前置: 无
 * 后置: 命中任一表返回中文名；否则返回 id 原文（id 为 null 时返回 null）
 * 异常: 无
 *
 * @param catalog 可手选技能目录（来自 store；`SkillPicker` 与页头共用同一份）
 * @param id 技能标识；null 表示「自动匹配」
 */
export function skillLabel(catalog: readonly SkillSummary[], id: string | null): string | null {
  if (id === null) return null;
  const found = catalog.find((skill) => skill.id === id);
  if (found !== undefined) return found.label;
  return INJECTED_SKILL_LABELS[id] ?? id;
}
