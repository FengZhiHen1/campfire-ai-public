import {useCurrentFrame} from 'remotion';
import {C, FONT_BODY, FONT_DISPLAY} from '../lib/tokens';
import {PageHead, Screen, TabBar} from './PhoneScreen';

// 档案页占位:内容取自 shot-list.md ④-a 走查记录与种子数据——
// 「待确认(1)」独立分组、AI 归纳来源可见、与已确认条目可辨;
// 待确认条目即纠正演示靶「疼痛与过载的区分压力」。

type Entry = {text: string; source: string};

const ConfirmedRow: React.FC<Entry> = ({text, source}) => (
  <div
    style={{
      backgroundColor: C.surface,
      border: `1px solid ${C.borderSoft}`,
      borderRadius: 14,
      padding: '11px 13px',
    }}
  >
    <div style={{fontSize: 14, color: C.fg, lineHeight: 1.5, fontFamily: FONT_BODY}}>{text}</div>
    <div style={{fontSize: 11, color: C.muted, marginTop: 6, fontFamily: FONT_BODY}}>{source}</div>
  </div>
);

const CandidateRow: React.FC<Entry & {frame: number}> = ({text, source, frame}) => (
  <div
    style={{
      backgroundColor: C.surfaceWarm,
      border: `1.5px dashed ${C.statusUnruled}`,
      borderRadius: 14,
      padding: '11px 13px',
    }}
  >
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <span
        style={{
          fontSize: 11,
          color: C.statusUnruled,
          border: `1px solid ${C.statusUnruled}`,
          borderRadius: 9999,
          padding: '1px 8px',
          fontFamily: FONT_BODY,
          flexShrink: 0,
        }}
      >
        待确认
      </span>
      <span style={{fontSize: 11, color: C.muted, fontFamily: FONT_BODY}}>{source}</span>
    </div>
    <div style={{fontSize: 14, color: C.fg, lineHeight: 1.5, marginTop: 8, fontFamily: FONT_BODY}}>
      {text}
    </div>
    <div style={{display: 'flex', gap: 18, marginTop: 10, fontSize: 13, fontFamily: FONT_BODY}}>
      <span style={{color: C.accent, fontWeight: 600}}>确认</span>
      <span style={{color: C.fg2}}>纠正</span>
      <span style={{color: C.fg2}}>删除</span>
    </div>
  </div>
);

export const ProfileScreen: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Screen>
      <PageHead />
      <div style={{padding: '8px 16px 0', flex: 1, overflow: 'hidden'}}>
        <div style={{fontFamily: FONT_DISPLAY, fontSize: 20, fontWeight: 500, color: C.fg}}>
          小满的档案
        </div>

        {/* 待确认分组置顶,RQ-MEM-04:推断不得冒充事实 */}
        <div style={{fontSize: 12, color: C.statusUnruled, marginTop: 14, fontFamily: FONT_BODY}}>
          待确认(1)
        </div>
        <div style={{marginTop: 8}}>
          <CandidateRow
            frame={frame}
            text="小满在难以区分疼痛与感官过载时,压力会显著上升"
            source="AI 归纳"
          />
        </div>

        <div style={{fontSize: 12, color: C.muted, marginTop: 16, fontFamily: FONT_BODY}}>
          已确认
        </div>
        <div style={{display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8}}>
          <ConfirmedRow
            text="噪音 + 人群叠加时容易捂住耳朵蹲下"
            source="监护人观察"
          />
          <ConfirmedRow
            text="先叫名字、再说一件具体的事,回应率更高"
            source="监护人观察"
          />
        </div>
      </div>
      <TabBar active="档案" />
    </Screen>
  );
};
