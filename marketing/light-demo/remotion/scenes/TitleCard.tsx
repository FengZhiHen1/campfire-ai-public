import {AbsoluteFill, Img, staticFile, useCurrentFrame, interpolate} from 'remotion';

// Title Card:篝火 logo 占位 + 产品名,验证暖米纸/火焰橙调性在视频里的观感。
// logo 资产到位前用纯排版占位(slogan 行),不虚构 UI。
export const TitleCard: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateRight: 'clamp',
  });
  const rise = interpolate(frame, [0, 20], [24, 0], {
    extrapolateRight: 'clamp',
    easing: (t) => 1 - Math.pow(1 - t, 3),
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: '#fbf6ee',
        justifyContent: 'center',
        alignItems: 'center',
        fontFamily:
          '"Noto Serif SC", "Songti SC", "STSong", "SimSun", Georgia, serif',
      }}
    >
      <div style={{opacity, transform: `translateY(${rise}px)`, textAlign: 'center'}}>
        <div
          style={{
            width: 88,
            height: 88,
            borderRadius: 24,
            backgroundColor: '#c2410c',
            margin: '0 auto 40px',
            // 篝火意象占位:橙色圆角块,真实 logo 进 assets/logo/ 后替换
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            fontSize: 44,
            color: '#fffdf8',
          }}
        >
          🔥
        </div>
        <h1 style={{fontSize: 96, color: '#201914', margin: 0, fontWeight: 500, letterSpacing: '0.06em'}}>
          篝火智答
        </h1>
        <p style={{fontSize: 30, color: '#7a6d63', margin: '28px 0 0', letterSpacing: '0.2em'}}>
          Campfire-AI · 让知识围着你燃烧
        </p>
      </div>
    </AbsoluteFill>
  );
};
