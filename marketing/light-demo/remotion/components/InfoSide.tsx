import {AbsoluteFill} from 'remotion';
import {C, FONT_BODY, FONT_DISPLAY} from '../lib/tokens';

export type InfoItem = {title: string; desc?: string};

// 构图 A 右侧信息区:奶油沙渐变底 + 错落入场的要点列表。
// appearAt(i) 由调用方按帧计算(0..1),组件本身不持有动画状态。
export const InfoSide: React.FC<{
  items: InfoItem[];
  appearAt: (i: number) => number;
}> = ({items, appearAt}) => (
  <AbsoluteFill style={{fontFamily: FONT_BODY}}>
    <div
      style={{
        position: 'absolute',
        right: 0,
        top: 0,
        bottom: 0,
        width: 780,
        background: `linear-gradient(135deg, ${C.surfaceWarm} 0%, ${C.bg} 100%)`,
      }}
    />
    <div style={{position: 'absolute', right: 120, top: 280, width: 560}}>
      {items.map((f, i) => {
        const t = appearAt(i);
        return (
          <div
            key={f.title}
            style={{
              opacity: t,
              transform: `translateY(${(1 - t) * 20}px)`,
              marginBottom: 64,
              paddingLeft: 28,
              borderLeft: `6px solid ${i === 0 ? C.accent : C.border}`,
            }}
          >
            <div
              style={{
                fontSize: 42,
                color: C.fg,
                fontWeight: 500,
                fontFamily: FONT_DISPLAY,
                letterSpacing: '0.02em',
              }}
            >
              {f.title}
            </div>
            {f.desc ? (
              <div style={{fontSize: 24, color: C.muted, marginTop: 10}}>{f.desc}</div>
            ) : null}
          </div>
        );
      })}
    </div>
  </AbsoluteFill>
);
