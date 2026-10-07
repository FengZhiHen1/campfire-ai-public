import {AbsoluteFill, Sequence} from 'remotion';
import {S1PainPoint} from './scenes/S1PainPoint';
import {S2Positioning} from './scenes/S2Positioning';
import {S3Emergency} from './scenes/S3Emergency';
import {S4Memory} from './scenes/S4Memory';
import {S5CaseLibrary} from './scenes/S5CaseLibrary';
import {S6Closing} from './scenes/S6Closing';
import {DUR, START} from './lib/timeline';
import {C} from './lib/tokens';

// 全片总装:六段按 lib/timeline.ts 的帧窗口排布,与 screenplay/narration.md 二稿一一对应。
// ③④⑤ 为占位 Capture(风格化近似屏),真实 Playwright 录屏到位后逐段替换。
export const Main: React.FC = () => {
  return (
    <AbsoluteFill style={{backgroundColor: C.bg}}>
      <Sequence from={START.S1} durationInFrames={DUR.S1}>
        <S1PainPoint />
      </Sequence>
      <Sequence from={START.S2} durationInFrames={DUR.S2}>
        <S2Positioning />
      </Sequence>
      <Sequence from={START.S3} durationInFrames={DUR.S3}>
        <S3Emergency />
      </Sequence>
      <Sequence from={START.S4} durationInFrames={DUR.S4}>
        <S4Memory />
      </Sequence>
      <Sequence from={START.S5} durationInFrames={DUR.S5}>
        <S5CaseLibrary />
      </Sequence>
      <Sequence from={START.S6} durationInFrames={DUR.S6}>
        <S6Closing />
      </Sequence>
    </AbsoluteFill>
  );
};
