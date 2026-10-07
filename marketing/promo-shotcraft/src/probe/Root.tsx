import {Composition} from 'remotion';
import {S8Cases} from '../shots/S8Cases';
export const ProbeRoot: React.FC = () => (
  <Composition id="S8" component={S8Cases} durationInFrames={390} fps={30} width={1920} height={1080} />
);
