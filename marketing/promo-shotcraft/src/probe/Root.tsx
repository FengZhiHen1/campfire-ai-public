// 探针入口:用于**单独抽某个镜头 / 某道题的帧**做视觉检查。
// 正片入口是 src/index.ts;本文件**不在正片路径上**(src/Root.tsx 不 import 探针)。
import {Composition} from 'remotion';

import {SHOTS} from '../timeline';
import {S1BrandOpen} from '../shots/S1BrandOpen';
import {S2PainPoint} from '../shots/S2PainPoint';
import {S3Positioning} from '../shots/S3Positioning';
import {S4Intake} from '../shots/S4Intake';
import {S5Analysis} from '../shots/S5Analysis';
import {S6ActionCard} from '../shots/S6ActionCard';
import {S7Memory} from '../shots/S7Memory';
import {S8Cases} from '../shots/S8Cases';
import {S9Closing} from '../shots/S9Closing';
import {EMERGENCY_QUESTIONS} from '../../../../apps/web/src/features/consult/domain/emergency';
import {ProbeAllQuestions} from './ProbeAllQuestions';

const SCENES: Record<string, React.FC> = {
  S1: S1BrandOpen, S2: S2PainPoint, S3: S3Positioning, S4: S4Intake,
  S5: S5Analysis, S6: S6ActionCard, S7: S7Memory, S8: S8Cases, S9: S9Closing,
};

export const ProbeRoot: React.FC = () => (
  <>
    {SHOTS.map((s) => {
      const Scene = SCENES[s.id];
      if (Scene === undefined) throw new Error(`探针缺少镜头实现: ${s.id}`);
      return (
        <Composition key={s.id} id={s.id} component={Scene}
          durationInFrames={s.duration} fps={30} width={1920} height={1080} />
      );
    })}
    {EMERGENCY_QUESTIONS.map((q, i) => (
      <Composition key={q.key} id={`Q${String(i + 1)}`} component={ProbeAllQuestions}
        durationInFrames={10} fps={30} width={1920} height={1080}
        defaultProps={{index: i}} />
    ))}
  </>
);
