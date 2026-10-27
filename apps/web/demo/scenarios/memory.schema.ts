/**
 * 模块: demo/scenarios/memory.schema
 * 职责: 场景「记忆：时间线、纠正、删除确认」的步骤声明与讲解词
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 场景清单与讲解词口径
 *   - apps/web/src/features/accounts/view/SettingsPage.tsx: MUST — 「我提过的事」入口（`/settings/memory`）
 *   - apps/web/src/features/memory/view/MemoryPage.tsx: MUST — 页头 `.sp-title`、日期分组 `details.tile.group-collapse`、
 *     条目 `article.list-row`、纠正表单 `h2#memory-correction-title`、删除确认单标题与正文（文案逐字来源）
 *   - apps/web/src/features/memory/domain/episodes.ts: MUST — 分组头「M月D日（N）」与 meta「发生时间 MM-DD HH:mm · 来自一次咨询」
 *   - apps/web/src/features/memory/domain/failures.ts: MUST — 纠正成功与中间态两条文案逐字来源
 * 边界:
 *   - 依赖: ../support/scenario（类型）
 *   - 被依赖: ./memory.spec；**尚未**在 ../support/paths.ts 的 `SCENARIO_SLUGS` 与 ./registry.ts 登记
 *     （本次任务边界：只写声明与脚本两个文件，登记与装配由另一处改动闭合）
 * 禁止行为:
 *   - 禁止在此文件里放截图逻辑（声明与执行分离：manifest 只信声明）
 *   - 禁止把「确认单出现」写成「删除已经发生」：本场景**不点**确认删除（删除不可逆）
 */

import type { DemoScenario } from '../support/scenario';

/**
 * 记忆：时间线、纠正、删除确认。
 *
 * `slug` 的类型 `ScenarioSlug` 目前只含**已登记**场景（`support/paths.ts` 的 `SCENARIO_SLUGS`）。
 * 本场景的登记**故意留在这两个文件之外**（任务边界：不改 `support/*.ts` 与 `registry.ts`），
 * 因此这一行在登记之前会报 `TS2322`、`apps/web/tests/demo-coverage.test.ts` 也会把这两个
 * 文件判成「未登记的孤儿」。这两处都是**如实暴露**的缺口，不在这里用类型断言消掉：
 * 消掉之后 `pnpm typecheck` 会绿，而场景永远不会成为材料——那才是真正的静默失败。
 */
export const MEMORY: DemoScenario = {
  slug: 'memory',
  title: '记忆：时间线、纠正、删除确认',
  claim:
    '记忆面没有创建端点：条目只能由产品写路径产生——模型在咨询里调用「记录记忆」→ 待写队列 → Worker 落库，' +
    '页面经 GET /api/memory/episodes 才读得到。本场景用真实写路径走通「说一件关于自己的事 → 时间线出现这条记录」，' +
    '再演示展开原文、纠正（撤下旧记录 + 写新记录）与删除二次确认（只到确认单，不真的删）。',
  steps: [
    {
      id: 'settings-memory-entry',
      caption: '设置页「关于你的数据」里的「我提过的事」——记忆页的入口；它是次级页，进去之后没有底部标签栏。',
    },
    {
      id: 'memory-timeline',
      caption:
        '记忆时间线：按日期倒序分组，每条都标着发生时间与「来自一次咨询」。' +
        '这条记录不是夹具种进去的，是刚才那次咨询里模型自己写下来的。',
    },
    {
      id: 'memory-expanded',
      caption: '展开一条记录看完整原文：本页是核对场景，内容不做摘要、不转译，展开后一字不少。',
    },
    {
      id: 'memory-correction-form',
      caption:
        '纠正表单预填了原文与发生时间。纠正不是「改」，而是撤下旧记录再写一条新的——' +
        '所以提交前先把说法改成更准确的那一版。',
    },
    {
      id: 'memory-correction-written',
      caption:
        '提交后提示「已新增一条更正，原记录不再作为依据」：原记录已从时间线撤下，新记录落在自己的日期分组里。',
    },
    {
      id: 'memory-delete-confirm',
      caption:
        '删除确认单说清了后果——「删除后咨询和历史都不会再用到它」。本场景只到这张单为止，不点确认（删除不可逆）。',
    },
  ],
};
