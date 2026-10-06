import {Composition} from 'remotion';
import {Main} from './Main';

// 视频基线:方案第 11.1 节 — 1920×1080@30fps、首期 ≤180s。
// 骨架阶段 Composition 先给 10s,scenes.yaml 接入后由脚本按旁白时长生成。
export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Main"
      component={Main}
      durationInFrames={300}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
