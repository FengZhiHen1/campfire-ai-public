/**
 * 模块: demo/scenarios/onboarding.schema
 * 职责: 场景「注册登录 → 首次咨询 → 引导建档」的步骤声明与讲解词
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 场景清单与讲解词口径
 *   - apps/web/src/features/accounts/view/LoginPage.tsx:176-202: MUST — 注册表单字段与提交按钮
 *   - apps/web/src/features/consult/view/MessageParts/QuestionCard.tsx:53-198: MUST — 提问卡形态
 *   - apps/api/skills/onboarding/SKILL.md: 引导是**多轮**的（逐题问答后才建档）
 * 边界:
 *   - 依赖: ../support/scenario（类型）
 *   - 被依赖: ./registry、./onboarding.spec、apps/web/tests/demo-coverage.test.ts
 * 禁止行为:
 *   - 禁止在此文件里放截图逻辑（声明与执行分离：manifest 只信声明）
 */

import type { DemoScenario } from '../support/scenario';

/** 注册登录 → 首次咨询 → 引导建档。 */
export const ONBOARDING: DemoScenario = {
  slug: 'onboarding',
  title: '注册登录 → 首次咨询 → 引导建档',
  claim:
    '新使用者凭邀请码开户，第一次提问即进入引导；第二轮就建出支持对象，档案随逐题问答累积。' +
    '（引导共十来问、一问一轮，本场景只走前两轮：材料要的是「发生了」，不是把十问答完。）',
  steps: [
    {
      id: 'login-entry',
      caption: '登录页：一期不发自助注册，入口是「已有邀请码？注册账号」。',
    },
    {
      id: 'register-filled',
      caption: '注册表单：账号名、密码与一次性邀请码三项齐备即可开户。',
    },
    {
      id: 'home-after-register',
      caption: '注册成功直接进首页；此时档案还是空的，提示从一件小事开始。',
    },
    {
      id: 'first-answer',
      caption: '首次咨询：先给出使用告知，再说明接下来要建档，并抛出第一组问题（工具行默认收起）。',
    },
    {
      id: 'guiding-question',
      caption: '引导提问卡：可以点选项，也可以用自己的话回答；每题都能跳过，不会当成「正常」。',
    },
    {
      id: 'guiding-round',
      caption: '答完继续下一问：引导一问一轮地推进，支撑对象已经建好，回答会被落成结构化记录。',
    },
    {
      id: 'profile-object',
      caption: '档案页：支持对象已经建好（本演示只走到第 2 轮，引导仍在继续）。',
    },
    {
      id: 'profile-records',
      caption: '档案记录按领域分组——「说一次话就留下结构化记录」的结果落到这里。',
    },
  ],
};
