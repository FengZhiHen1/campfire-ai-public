import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';

// 构图 A 验证:手机设备框居左,右侧品牌背景 + 要点文字(侧信息区)。
// 这是全片主视觉骨架——各 Demo 场景组件都会复用这套布局常量。
const PHONE_W = 420; // 演示时手机内容区逻辑宽度(390 逻辑 × 1.08 放大)
const PHONE_H = 912;
const PHONE_X = 360; // 手机中心点(左缘 150,完整在画内)
const PHONE_Y = 540;

const FEATURES = [
  {title: 'RAG 案例库', desc: '真实案例,情境检索'},
  {title: 'Agent 工具链', desc: '十个产品工具,权限门控'},
  {title: '长期记忆', desc: 'Graphiti 知识图谱'},
];

export const LayoutPreview: React.FC = () => {
  const frame = useCurrentFrame();
  const phoneIn = interpolate(frame, [0, 25], [-60, 0], {
    extrapolateRight: 'clamp',
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });
  const textIn = (i: number) =>
    interpolate(frame, [20 + i * 8, 34 + i * 8], [0, 1], {
      extrapolateRight: 'clamp',
    });

  return (
    <AbsoluteFill style={{backgroundColor: '#fbf6ee', fontFamily: 'system-ui, "PingFang SC", sans-serif'}}>
      {/* 右侧暖色信息区底 */}
      <div
        style={{
          position: 'absolute',
          right: 0,
          top: 0,
          bottom: 0,
          width: 780,
          background: 'linear-gradient(135deg, #f1e3cf 0%, #fbf6ee 100%)',
        }}
      />

      {/* 手机设备框(居左) */}
      <div
        style={{
          position: 'absolute',
          left: PHONE_X - PHONE_W / 2,
          top: PHONE_Y - PHONE_H / 2,
          width: PHONE_W,
          height: PHONE_H,
          borderRadius: 56,
          backgroundColor: '#201914',
          padding: 14,
          transform: `translateX(${phoneIn}px)`,
          boxShadow: '0 40px 80px rgba(32, 25, 20, 0.25)',
        }}
      >
        <div
          style={{
            width: '100%',
            height: '100%',
            borderRadius: 44,
            backgroundColor: '#fffdf8',
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            alignItems: 'center',
          }}
        >
          {/* 屏幕内容占位:真实 Playwright 素材以 <OffthreadVideo> 替换 */}
          <span style={{fontSize: 26, color: '#7a6d63'}}>H5 屏幕内容占位</span>
        </div>
      </div>

      {/* 右侧要点文字(错落入场) */}
      <div
        style={{
          position: 'absolute',
          right: 120,
          top: 240,
          width: 560,
        }}
      >
        {FEATURES.map((f, i) => (
          <div
            key={f.title}
            style={{
              opacity: textIn(i),
              transform: `translateY(${(1 - textIn(i)) * 20}px)`,
              marginBottom: 56,
              paddingLeft: 28,
              borderLeft: `6px solid ${i === 0 ? '#c2410c' : '#ded2c3'}`,
            }}
          >
            <div style={{fontSize: 40, color: '#201914', fontWeight: 600}}>{f.title}</div>
            <div style={{fontSize: 24, color: '#7a6d63', marginTop: 8}}>{f.desc}</div>
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};
