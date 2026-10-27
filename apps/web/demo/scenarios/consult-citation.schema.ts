/**
 * 模块: demo/scenarios/consult-citation.schema
 * 职责: 场景「日常咨询 → RAG 检索 → 引用回指」的步骤声明与讲解词
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 场景清单与讲解词口径；第 8 节「引用回指当前不可演示」
 *   - apps/web/src/shared/types/sse.ts:79-86: MUST — `CitationRecord` 只有 citation_id / run_id /
 *     source / reference / recorded_at / summary，**没有 item_id**
 *   - apps/web/src/features/consult/view/MessageParts/CitationPart.tsx:33-37: MUST — `citationDeepLink()`
 *     在缺 `item_id` 时返回 null，于是标题退化成 `citation.reference`、来源行追加
 *     「本条暂不能跳转到来源条目」
 *   - apps/web/src/features/consult/view/MessageParts/toolLabels.ts:38-49: MUST —
 *     `search_knowledge` →「查阅资料」、`search_cases` →「查阅案例」
 * 边界:
 *   - 依赖: ../support/scenario（类型）
 *   - 被依赖: ./registry、./consult-citation.spec、apps/web/tests/demo-coverage.test.ts
 * 禁止行为:
 *   - 禁止在此文件里放截图逻辑（声明与执行分离：manifest 只信声明）
 *   - 禁止把「点开依据能定位到来源条目」写成讲解词——产品当前不具备该能力，
 *     界面逐条写着「本条暂不能跳转到来源条目」；那样写就是让讲解词与截图互相打脸
 */

import type { DemoScenario } from '../support/scenario';

/** 日常咨询 → RAG 检索 → 引用回指。 */
export const CONSULT_CITATION: DemoScenario = {
  slug: 'consult-citation',
  title: '日常咨询 → RAG 检索 → 引用回指',
  claim:
    '日常咨询里模型先检索再作答：工具行证明「查阅资料」「查阅案例」真的被调用，回答尾部挂出依据区；' +
    '但依据只有 `knowledge:<uuid>` 这类内部标识、逐条注明「本条暂不能跳转到来源条目」——' +
    '链路通到检索与呈现，断在 `CitationRecord` 缺 `item_id` 的回指上。',
  steps: [
    {
      id: 'consult-entry',
      caption: '进入日常咨询：不选技能也能直接开口，入口就是「开始新的日常咨询」。',
    },
    {
      id: 'question-submitted',
      caption: '提出一件具体的日常困扰（孩子出门容易走丢，平时怎么防）——这句话作为这条会话的第一条消息发出去。',
    },
    {
      id: 'answer-first-token',
      caption: '回答开始逐字输出：正文按段落排版，先确认听懂了什么，再谈怎么办。',
    },
    {
      id: 'retrieval-tool-row',
      caption: '工具行显示「查阅资料」「查阅案例」——建议之前先检索，检索是真发生的，不是嘴上说「有据」。',
    },
    {
      id: 'answer-complete',
      caption: '完整回答：建议与适用范围都写在正文里，段落排版就是使用者看到的最终形态。',
    },
    {
      id: 'citation-block',
      caption:
        '展开依据区：逐条给出标题与来源；但标题是 knowledge:<uuid> 这类内部标识，' +
        '每一条都注明「本条暂不能跳转到来源条目」——回指断在依据载荷缺 item_id 上，这是产品缺口，不是没做演示。',
    },
  ],
};
