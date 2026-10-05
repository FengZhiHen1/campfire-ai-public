/**
 * 模块: features/consult/view/MessageParts/toolLabels
 * 职责: 工具标识符 → 面向使用者的中文友好名的映射（含兜底），工具行文案的唯一词表
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 契约修订 7（`.tool-row` 显示「查阅资料（2 条）」样式，
 *     即面向使用者的名称，而不是线上标识符）
 *   - apps/api/src/campfire/surfaces/consult/registry.py: MUST — 一期十个产品工具的标识符
 *     （`build_product_tools`，注册清单的真源）
 *   - apps/api/src/campfire/agent/tools/pool.py: MUST — 三个基座保留名工具，也会发出 tool_call 事件
 *   - docs/design/pages/档案页.md: MUST — 使用者可见术语用「支持对象」「档案」
 * 边界:
 *   - 依赖: 无（纯词表）
 *   - 被依赖: view/MessageParts/ToolIndicator
 * 禁止行为:
 *   - 禁止在查不到映射时回退成标识符（那正是 OBS-01 的形态：界面暴露内部名称）
 *   - 禁止把这里当中文翻译表以外的东西用（不做权限判断、不做可用性判断）
 *
 * 为什么在 view 层而不是从服务端取：与同目录既有的 `domain/actionCard.ts`
 * （`STATE_VALUE_LABELS`、`SOURCE_LABELS`）同一种做法——线上标识符到中文显示名的映射
 * 是呈现决定，不是业务事实，服务端契约里没有这个字段（HTTP 与 SSE 契约第 7 节的
 * tool_call part 只有 `tool_name` / `ok` / `summary`）。
 *
 * 为什么名称要与标识符分开：「工具名是线上标识符，原样显示」的旧注释与设计真源冲突
 * ——`docs/design/pages/对话页.md:60` 给的是「查阅资料（2 条）」这种面向使用者的措辞。
 * 同一行里「展开/收起」本来就是中文，一半中文一半标识符本身就是漏项的证据。
 */

/**
 * 工具标识符 → 中文友好名。
 *
 * 键集合必须覆盖两个来源的并集：
 * 1. 产品侧十个工具（`registry.build_product_tools`）；
 * 2. 基座三个保留名工具（`pool.RESERVED_TOOL_NAMES`）——它们同样经
 *    `ToolBridge` 发 `tool_call_started/finished`，因此在界面上同样会开出 `.tool-row`。
 *
 * 完整性由 `apps/api/tests/test_tool_labels_coverage.py` 机械核对（新增工具而未加映射 ⇒ 红）。
 */
export const TOOL_LABELS: Readonly<Record<string, string>> = {
  // --- 产品侧工具（registry.build_product_tools）---
  create_support_object: '建立支持对象',
  emit_emergency_action_card: '生成行动卡',
  finish_onboarding: '完成引导',
  propose_profile_item: '整理档案',
  read_memory: '回看记忆',
  read_profile_items: '查看档案记录',
  read_profile_summary: '查看档案摘要',
  search_cases: '查阅案例',
  search_knowledge: '查阅资料',
  write_memory: '记录记忆',
  // --- 基座保留名工具（pool.RESERVED_TOOL_NAMES）---
  ask_user: '向你提问',
  read_skill_resource: '读取技能资料',
  skill: '启用技能',
};

/**
 * 查不到映射时的中性兜底文案。
 *
 * 为什么不是标识符：露出 `some_new_tool · 已结束` 就是 OBS-01 本身。
 * 为什么不是空串：空串会让「工具行没渲染出来」与「这是个还没起名的工具」在界面上无法区分。
 * 取一个描述「这里发生过一次操作」的中性词，配合状态后缀读作「其他操作 · 已结束」——
 * 使用者不会以为自己在看一个泄漏的内部名，也不会误以为操作没发生。
 */
export const FALLBACK_TOOL_LABEL = '其他操作';

/**
 * 取工具行的名称。
 *
 * 前置: 无
 * 后置: 命中词表返回中文名；未命中返回 {@link FALLBACK_TOOL_LABEL}（**绝不**返回标识符）
 * 异常: 无
 *
 * @param toolName 线格式里的工具标识符（`tool_call_started.tool_name`）
 */
export function toolDisplayName(toolName: string): string {
  return TOOL_LABELS[toolName] ?? FALLBACK_TOOL_LABEL;
}

/** 词表覆盖的工具标识符集合（测试与完整性核对用；读取方不得就地修改）。 */
export const MAPPED_TOOL_NAMES: readonly string[] = Object.keys(TOOL_LABELS);
