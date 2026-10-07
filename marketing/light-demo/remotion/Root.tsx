import {Composition} from 'remotion';
import {Main} from './Main';
import {FPS, TOTAL_FRAMES} from './lib/timeline';

// 视频基线:1920×1080@30fps,全长 175s(TOTAL_FRAMES 由 lib/timeline.ts 六段派生)。
export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Main"
      component={Main}
      durationInFrames={TOTAL_FRAMES}
      fps={FPS}
      width={1920}
      height={1080}
    />
  );
};
