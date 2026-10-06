import {AbsoluteFill, Sequence, useCurrentFrame} from 'remotion';
import {TitleCard} from './scenes/TitleCard';
import {LayoutPreview} from './scenes/LayoutPreview';

// 骨架验证时间线:0-3s Title Card,3-10s 构图 A(设备框 + 侧信息区)占位。
// 只验证工具链与构图,不含真实素材;scenes.yaml 接入后重写为数据驱动。
export const Main: React.FC = () => {
  return (
    <AbsoluteFill style={{backgroundColor: '#fbf6ee'}}>
      <Sequence from={0} durationInFrames={90}>
        <TitleCard />
      </Sequence>
      <Sequence from={90} durationInFrames={210}>
        <LayoutPreview />
      </Sequence>
    </AbsoluteFill>
  );
};
