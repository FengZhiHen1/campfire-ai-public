// 探针:逐题验证 EmergencyFormView 能渲染**全部 8 道题**(含三种控件类型)。
//
// 为什么单独验:目标的「8 道题逐屏」在组件架构下不再靠截图,而是靠渲染真实题目数据。
// 那么必须确认 8 道题的每一种控件(multi / single / text)都能正确渲染 ——
// 尤其 text 型(what_happened)与带 allowNote 的题,它们走的分支不同。
import {AbsoluteFill, useCurrentFrame} from 'remotion';

import {DeviceStage, FilmRoot} from '../lib/DeviceStage';
import {EmergencyFormView} from '../lib/EmergencyFormView';
import {EMERGENCY_QUESTIONS} from '../../../../apps/web/src/features/consult/domain/emergency';

/** 每题给一个能同时展示「已选态」与「补充文本」的样例作答。 */
const SAMPLE: Record<string, string[]> = {
  medical_red_flags: ['obvious_pain'],
  baseline_deviation: ['mild'],
  communication: ['reduced'],
  distress: ['moderate'],
  sensory_environment: ['noise', 'crowd'],
  what_happened: [],
  primary_risk: ['elopement'],
  possible_pain: ['yes'],
};

export const ProbeAllQuestions: React.FC<{index: number}> = ({index}) => {
  useCurrentFrame();
  const q = EMERGENCY_QUESTIONS[index];
  if (q === undefined) throw new Error(`题号越界: ${index}`);
  return (
    <FilmRoot>
      <DeviceStage cx={640} cy={540} scrollY={9999}>
        <EmergencyFormView
          question={q}
          index={index}
          total={EMERGENCY_QUESTIONS.length}
          selected={SAMPLE[q.key] ?? []}
          note={q.control === 'text' ? '在超市突然蹲下捂住耳朵' : ''}
          showNote={q.allowNote === true}
          handled={index + 1}
        />
      </DeviceStage>
    </FilmRoot>
  );
};
