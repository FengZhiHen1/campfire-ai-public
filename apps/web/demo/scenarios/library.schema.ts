/**
 * 模块: demo/scenarios/library.schema
 * 职责: 场景「案例库与资料分区（读物排版）」的步骤声明与讲解词
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 场景清单、讲解词口径与「三处清单同时改」的登记要求
 *   - apps/web/src/app/routes.tsx:115-120: MUST — 唯一路由 `/cases`（没有 `/cases/:id` 详情页）
 *   - apps/web/src/features/library/view/LibraryPage.tsx:76-114,226-318: MUST — 页头 `.sp-title`、
 *     检索范围 `role=group`、结果行 `article.list-row`、`aria-controls="library-body-<id>"`
 *   - apps/web/src/shared/ui/ReadableText.tsx:22-46: MUST — `.readable-paragraph/-heading/-list/-quote`
 *   - data/cases/2026-11-06_1000_fictional-supermarket-meltdown/manifest.json: 本场景选用的虚构演示案例与检索词
 * 边界:
 *   - 依赖: ../support/scenario（类型）
 *   - 被依赖: ./registry、./library.spec、apps/web/tests/demo-coverage.test.ts
 * 禁止行为:
 *   - 禁止在此文件里放截图逻辑（声明与执行分离：manifest 只信声明）
 *   - 禁止声明「需要模型的镜头」：本场景是纯浏览，不该因模型额度把材料拖成红的
 */

import type { DemoScenario } from '../support/scenario';

/** 案例库与资料分区（读物排版）。 */
export const LIBRARY: DemoScenario = {
  slug: 'library',
  title: '案例库与资料分区（读物排版）',
  claim:
    '案例与资料两个分区在同一个 `/cases` 路由上靠查询参数切换，检索词直接打到真检索链；' +
    '命中后就地展开、按读物排版呈现正文，来源与适用范围收在折叠块里，引用深链还能跳回原条目并定位展开。' +
    '（这条链路不需要模型与对话，纯浏览即可证明「读资料」这一侧可用。）',
  steps: [
    {
      id: 'case-list',
      caption: '案例库列表：`/cases` 默认落在案例分区，一条一张卡，标题、摘要与状态徽章先给扫读。',
    },
    {
      id: 'case-expand',
      caption: '就地展开：点一下卡片，正文按读物排版展开（小节标题、段落、列表、引语），没有单独的详情页。',
    },
    {
      id: 'source-scope',
      caption: '来源与适用范围：来源类型、证据档、审阅与授权记录收在折叠块里，扫读时不必挤占标题。',
    },
    {
      id: 'knowledge-list',
      caption: '资料库列表：同一路由换成 `?section=knowledge`，页头与检索框随之变成「资料库」/「搜索资料」。',
    },
    {
      id: 'case-search',
      caption: '检索命中：输入「节奏调整」就命中那条访谈案例——走的是真检索链，不是前端过滤。',
    },
    {
      id: 'case-deeplink',
      caption: '深链定位：`?item=<条目 id>` 从引用跳回原条目，仍在这一页里定位并就地展开。',
    },
  ],
};
