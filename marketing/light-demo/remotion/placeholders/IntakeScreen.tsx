import {useCurrentFrame} from 'remotion';
import {C, FONT_BODY} from '../lib/tokens';
import {
  ChoiceTile,
  PrimaryButton,
  ProgressTrack,
  QuietButton,
  Screen,
  ScreenTitle,
  SubpageHead,
} from './PhoneScreen';

// 应急采集占位(第 3/8 题):按 docs/design/pages/应急表单页.md——
// 一屏一题分步流、细进度条、「跳过 = 未排除」提示常驻、跳过与下一题并排。
export const IntakeScreen: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Screen>
      <SubpageHead back="退出应急" />
      <ProgressTrack ratio={3 / 8} />
      <ScreenTitle
        title="现在的情况"
        hint="跳过 = 未排除,不会当作正常"
        withFlame
        frame={frame}
      />
      <div style={{padding: '26px 20px 0', flex: 1}}>
        <div style={{fontSize: 19, color: C.fg, fontFamily: FONT_BODY, marginBottom: 18, lineHeight: 1.5}}>
          现在能不能和你沟通?
        </div>
        <div style={{display: 'flex', flexDirection: 'column', gap: 12}}>
          <ChoiceTile label="能,和平时差不多" />
          <ChoiceTile label="比平时差,但还有回应" selected />
          <ChoiceTile label="完全没有回应" />
        </div>
      </div>
      <div style={{padding: '0 20px 26px', display: 'flex', alignItems: 'center', gap: 8}}>
        <div style={{flex: 1}}>
          <QuietButton label="跳过这题" />
        </div>
        <div style={{flex: 2}}>
          <PrimaryButton label="下一题" />
        </div>
      </div>
    </Screen>
  );
};
