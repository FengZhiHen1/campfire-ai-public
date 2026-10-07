import {useCurrentFrame} from 'remotion';
import {C, FONT_BODY, FONT_DISPLAY} from '../lib/tokens';
import {FlameDot} from '../lib/brand';
import {PageHead, PrimaryButton, Screen, TabBar} from './PhoneScreen';

// 首页占位:按 docs/design/pages/首页.md——应急入口唯一视觉最重(橙描边 + 呼吸点),
// 日常入口为纸面卡片,次级入口两张 mini-card,底部 tab 栏。
export const HomeScreen: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Screen>
      <PageHead />
      <div style={{padding: '14px 16px 0', display: 'flex', flexDirection: 'column', gap: 16}}>
        {/* 应急入口 */}
        <div
          style={{
            border: `1.5px solid ${C.accent}`,
            borderRadius: 24,
            backgroundColor: C.surface,
            padding: '18px 18px 16px',
          }}
        >
          <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
            <FlameDot frame={frame} size={13} />
            <span style={{fontFamily: FONT_DISPLAY, fontSize: 21, fontWeight: 500, color: C.fg}}>
              现在需要帮助
            </span>
          </div>
          <div style={{fontSize: 14, color: C.fg2, marginTop: 10, lineHeight: 1.5, fontFamily: FONT_BODY}}>
            在现场遇到正在发生的情况?回答几个问题,马上给你可行动的建议
          </div>
          <div style={{marginTop: 14, width: 190, marginLeft: 'auto'}}>
            <PrimaryButton label="开始应急咨询" />
          </div>
        </div>

        {/* 日常咨询入口 */}
        <div
          style={{
            border: `1px solid ${C.border}`,
            borderRadius: 16,
            backgroundColor: C.surface,
            padding: '16px 18px',
          }}
        >
          <div style={{fontFamily: FONT_DISPLAY, fontSize: 19, fontWeight: 500, color: C.fg}}>
            日常咨询
          </div>
          <div style={{fontSize: 13, color: C.fg2, marginTop: 6, fontFamily: FONT_BODY}}>
            想聊聊正在准备或刚发生的事,随时开始
          </div>
        </div>

        {/* 次级入口行 */}
        <div style={{display: 'flex', gap: 12}}>
          {[
            {t: '案例库', d: '看看别的家庭怎么处理类似情况'},
            {t: '资料库说明', d: '每条建议都标来源与适用范围'},
          ].map((m) => (
            <div
              key={m.t}
              style={{
                flex: 1,
                borderRadius: 16,
                backgroundColor: C.surfaceWarm,
                padding: '13px 14px',
              }}
            >
              <div style={{fontSize: 14, fontWeight: 600, color: C.fg, fontFamily: FONT_BODY}}>{m.t}</div>
              <div style={{fontSize: 12, color: C.fg2, marginTop: 5, lineHeight: 1.45, fontFamily: FONT_BODY}}>
                {m.d}
              </div>
            </div>
          ))}
        </div>
      </div>
      <TabBar active="首页" />
    </Screen>
  );
};
