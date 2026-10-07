import {AbsoluteFill, Audio, interpolate, Sequence, staticFile} from 'remotion';
import {SHOTS, TOTAL} from './timeline';
import {C} from './tokens';
import {SFX} from './sfx';
import {SFX_LEAD_FRAMES} from './sfxLead.generated';
import {S1BrandOpen} from './shots/S1BrandOpen';
import {S2PainPoint} from './shots/S2PainPoint';
import {S3Positioning} from './shots/S3Positioning';
import {S4Intake} from './shots/S4Intake';
import {S5Analysis} from './shots/S5Analysis';
import {S6ActionCard} from './shots/S6ActionCard';
import {S7Memory} from './shots/S7Memory';
import {S8Cases} from './shots/S8Cases';
import {S9Closing} from './shots/S9Closing';

const SCENES: Record<string, React.FC> = {
  S1: S1BrandOpen,
  S2: S2PainPoint,
  S3: S3Positioning,
  S4: S4Intake,
  S5: S5Analysis,
  S6: S6ActionCard,
  S7: S7Memory,
  S8: S8Cases,
  S9: S9Closing,
};

export const Promo: React.FC<{bgm?: boolean}> = ({bgm = true}) => {
  return (
    <AbsoluteFill style={{backgroundColor: C.bg}}>
      {SHOTS.map((s) => {
        const Scene = SCENES[s.id];
        return (
          <Sequence key={s.id} from={s.from} durationInFrames={s.duration}>
            <Scene />
          </Sequence>
        );
      })}

      {/* BGM:音量包络 1s 淡入→0.30→2s 淡出,bgm prop 控制有无 */}
      {bgm ? (
        <Audio
          src={staticFile('audio/bgm-tech-house.mp3')}
          volume={(f) =>
            interpolate(f, [0, 30, TOTAL - 60, TOTAL], [0, 0.3, 0.3, 0], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            })
          }
        />
      ) : null}

      {/* SFX 钉帧表。
          ★ `trimBefore`:跳过素材开头的静音,让**瞬态落在 cue 帧上**。
            素材开头不是从 0 就开始响的 —— 实测 16 个里 11 个有静音,最长 488ms
            (`data-stream`)。若不裁,声音实际响起的时刻 = cue 帧 + 素材自带延迟,
            而且每条延迟不同 ⇒ 听起来不是「整体偏晚」而是「每条偏得不一样」。
            数值由 verify/sfx-lead.py 从素材实测生成,并由它校验(不一致即 exit 1)。 */}
      {SFX.map((s, i) => (
        <Sequence key={i} from={s.from} durationInFrames={s.durationInFrames}>
          <Audio
            src={staticFile(`audio/sfx/${s.src}.mp3`)}
            volume={s.volume}
            trimBefore={SFX_LEAD_FRAMES[s.src] ?? 0}
          />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
