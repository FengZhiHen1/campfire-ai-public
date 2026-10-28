/**
 * 模块: demo/scenarios/consult-citation.schema
 * 职责: 场景「日常咨询 → RAG 检索 → 引用回指」的步骤声明与讲解词
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 场景清单与讲解词口径；第 8 节「引用回指当前不可演示」
 *   - apps/web/src/features/consult/view/MessageParts/CitationPart.tsx: MUST — 深链从 `reference` 的
 *     `<库别>:<标识>` 前缀推出（2026-10-28 起），标题优先显示 `summary`（后端写入时取条目标题），
 *     拿不到标识时才退回纯文本并注明「本条暂不能跳转到来源条目」
 *   - apps/api/src/campfire/tools/library.py: MUST — `reference` 的线格式与「摘要取标题」的约定
 *   - apps/web/src/features/consult/view/MessageParts/toolLabels.ts:38-49: MUST —
 *     `search_knowledge` →「查阅资料」、`search_cases` →「查阅案例」
 * 边界:
 *   - 依赖: ../support/scenario（类型）
 *   - 被依赖: ./registry、./consult-citation.spec、apps/web/tests/demo-coverage.test.ts
 * 禁止行为:
 *   - 禁止在此文件里放截图逻辑（声明与执行分离：manifest 只信声明）
 *   - 禁止把讲解词写成产品做不到的事：回指**已可用**（2026-10-28），所以最后一帧必须真的
 *     点进去并落到那一条；哪天链路断了，这一帧会红，而不是让讲解词继续替它圆场
 */

import type { DemoScenario } from '../support/scenario';

/** 日常咨询 → RAG 检索 → 引用回指。 */
export const CONSULT_CITATION: DemoScenario = {
  slug: 'consult-citation',
  title: '日常咨询 → RAG 检索 → 引用回指',
  claim:
    '日常咨询里模型先检索再作答：工具行证明「查阅资料」「查阅案例」真的被调用，回答尾部挂出依据区，' +
    '每条依据带标题与库别，点标题直接落到案例库/资料库里那一条——检索、呈现、回指三段都通。',
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
      caption: '展开依据区：逐条给出条目标题与来源库别（knowledge = 资料库，case = 案例库），标题本身是可以点的链接。',
    },
    {
      id: 'citation-deeplink',
      caption:
        '点开第一条依据：跳到案例库浏览页的那一条，正文展开、来源与适用范围都在原处——依据不是装饰，' +
        '回指确实落到了条目本身。',
    },
  ],
};
