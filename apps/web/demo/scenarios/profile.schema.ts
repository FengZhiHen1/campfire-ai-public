/**
 * 模块: demo/scenarios/profile.schema
 * 职责: 场景「档案页 → 新建支持对象 → 手动补一条记录 → 对象切换与草稿保护」的步骤声明与讲解词
 * 数据来源:
 *   - docs/运维/演示材料生成.md: MUST — 场景清单与讲解词口径（步骤顺序即演示顺序）
 *   - apps/web/src/features/profile/view/ProfilePage.tsx:33-81: MUST — 页面文案（空态、补充表单、切换确认单）
 *   - apps/web/src/features/profile/domain/formValidation.ts:57-70: 草稿判据（领域被选过也算改动）
 * 边界:
 *   - 依赖: ../support/scenario（类型）
 *   - 被依赖: ./profile.spec（待登记进 ./registry 与 ../support/paths 的 SCENARIO_SLUGS 之后才是材料）
 * 禁止行为:
 *   - 禁止在此文件里放截图逻辑（声明与执行分离：manifest 只信声明）
 *   - 禁止把讲解词写成「按钮点得动」这类过程描述（讲解词说的是使用者视角发生了什么）
 */

import type { DemoScenario } from '../support/scenario';

/** 档案页：对象切换、字段补充、草稿保护。 */
export const PROFILE: DemoScenario = {
  slug: 'profile',
  title: '档案：对象切换、字段补充、草稿保护',
  claim:
    '新账号在档案页自己建支持对象、手动补一条记录；有未保存草稿时切换对象会被拦下，而不是静默丢弃；' +
    '刷新页面后那条记录仍在——留下的是数据，不是一句成功提示。',
  steps: [
    {
      id: 'profile-empty',
      caption: '全新账号第一次进档案页：还没有支持对象，页面上唯一的入口是「+ 新建对象」。',
    },
    {
      id: 'object-form',
      caption: '新建对象弹层：称呼只是你在界面上认出 TA 的名字，填好就能创建。',
    },
    {
      id: 'object-created',
      caption: '对象建好：切换器出现第一个 chip，摘要区还是空的——建档与记录是两件事。',
    },
    {
      id: 'entry-form',
      caption: '点「补充一条」就地展开表单：领域可选，主题与描述由你自己写，不是咨询推断出来的。',
    },
    {
      id: 'entry-saved',
      caption: '保存成功：提示「已补充一条记录」，条目落进「感觉处理」分组。',
    },
    {
      id: 'second-object',
      caption: '再建一个对象：切换器里两个 chip 平级单选，切换是就地换内容，不是跳页面。',
    },
    {
      id: 'draft-guard',
      caption: '有未保存草稿时点另一个对象：先问一句「切换支持对象？」，草稿不会被静默丢掉。',
    },
    {
      id: 'after-reload',
      caption: '刷新页面后记录仍在——写进去的是数据，提示语本身刷新即消失。',
    },
  ],
};
