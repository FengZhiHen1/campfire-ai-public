/**
 * 模块: demo/scenarios/emergency.schema
 * 职责: 场景「应急咨询 → 八维表单 → 行动卡」的步骤声明与讲解词
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 场景清单与讲解词口径（`caption` 是展示时直接念的那句话）
 *   - apps/web/src/features/consult/view/EmergencyFormPage.tsx:64-179: MUST — 页头标题、退出按钮、
 *     进度条、题干、选项组、跳过/下一题/提交按钮与两句固定文案
 *   - apps/web/src/features/consult/domain/emergency.ts:49-153、:166: MUST — 八维 key 与取值、跳过语义
 *   - apps/web/src/features/consult/view/MessageParts/ActionCard.tsx:68-102: MUST — 行动卡分节与医疗风险徽章
 *   - apps/api/src/campfire/surfaces/consult/injections.py:63-111: MUST — 首条采集消息的三处标记
 * 边界:
 *   - 依赖: ../support/scenario（类型）、../support/paths（slug 联合类型）
 *   - 被依赖: ./emergency.spec、以及登记之后的 ./registry 与 tests/demo-coverage.test.ts
 * 禁止行为:
 *   - 禁止在此文件里放截图逻辑（声明与执行分离：manifest 只信声明）
 *   - 禁止在讲解词里写诊断、用药、自伤/伤人细节（真栈材料只陈述可观察事实）
 */

import type { DemoScenario } from '../support/scenario';

/** 应急咨询 → 八维表单 → 行动卡。 */
export const EMERGENCY: DemoScenario = {
  // `SCENARIO_SLUGS`（support/paths.ts:85）目前只登记了 onboarding，而本次任务只允许新增
  // 本场景的 schema 与 spec 两个文件、不得改 support/paths.ts。故这里先断言成联合类型让声明落盘；
  // 登记完成后应删掉这处断言（届时它已不再必要）——登记缺失会让 manifest 与
  // tests/demo-coverage.test.ts 都把本场景判成缺口，那不是本文件能自愈的事。
  slug: 'emergency',
  title: '应急咨询 → 八维表单 → 行动卡',
  claim:
    '现场入口把八维采集（八项全可跳过、跳过即「未排除」）变成一次真实运行，' +
    '回来后由结构化工具产出一张带分节与医疗风险徽章的行动卡——证明「表单 → 会话 → 行动卡」' +
    '整条链路在真模型上可用，而不只是「提交成功」。',
  steps: [
    {
      id: 'home-emergency-entry',
      caption: '现场遇到正在发生的情况时，入口就在首页：「开始应急咨询」。',
    },
    {
      id: 'form-first-question',
      caption:
        '应急表单第 1 题：先问医疗危险表现，可多选；一屏一题，进度条显示这是 8 题里的第 1 题。',
    },
    {
      id: 'form-skip-progress',
      caption: '不确定就跳过：跳过等于未排除，不会被当成「正常」；进度随之前进到第 3 题。',
    },
    {
      id: 'form-observation-filled',
      caption:
        '「刚刚发生了什么」只写一句看得见的事实——在超市里，音乐一响就捂住耳朵、站在原地不动；不写判断，也不写诊断。',
    },
    {
      id: 'form-last-skipped',
      caption:
        '最后一题同样可以跳过，页脚随即标注「本题已跳过（按未排除处理）」；八题不必答完，随时可以提交。',
    },
    {
      id: 'thread-intake',
      caption:
        '提交即建会话：八项原样落成首条采集消息，跳过的写成「已跳过（未排除）」，这一轮立刻开始分析。',
    },
    {
      id: 'action-card-sections',
      caption:
        '分析回来后是一张现场行动卡：分节并逐节给序号，医疗风险走语义徽章，不写诊断、也不给用药。',
    },
  ],
};
