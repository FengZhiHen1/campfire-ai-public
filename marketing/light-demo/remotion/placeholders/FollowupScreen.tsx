import {useCurrentFrame} from 'remotion';
import {C, FONT_BODY} from '../lib/tokens';
import {
  CheckRow,
  PrimaryButton,
  Screen,
  ScreenTitle,
  SubpageHead,
} from './PhoneScreen';

// 追问占位:走查记录③-c 确认追问是一键选择的勾选卡片、快速过题。
// 勾选项取自走查实测的一套选择(环境 = 噪音 + 人群)。
export const FollowupScreen: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Screen>
      <SubpageHead back="返回" />
      <ScreenTitle
        title="再确认两件事"
        hint="只问会改变建议的项"
        withFlame
        frame={frame}
      />
      <div style={{padding: '26px 20px 0', flex: 1}}>
        <div style={{fontSize: 19, color: C.fg, fontFamily: FONT_BODY, marginBottom: 14, lineHeight: 1.5}}>
          周围环境里有没有这些?
        </div>
        <div style={{display: 'flex', flexDirection: 'column', gap: 2}}>
          <CheckRow label="噪音" checked />
          <CheckRow label="灯光刺眼" />
          <CheckRow label="人群密集" checked />
          <CheckRow label="温度不适" />
        </div>
      </div>
      <div style={{padding: '0 20px 26px'}}>
        <PrimaryButton label="提交,开始分析" />
      </div>
    </Screen>
  );
};
