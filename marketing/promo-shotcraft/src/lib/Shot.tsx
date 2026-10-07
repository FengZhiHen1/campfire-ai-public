// Shot —— 影片镜头版式:左侧真实设备、右侧纸面说明区。
//
// 为什么抽成组件(而不是每个镜头各写一遍):
//   旧版九个镜头各自手写「设备框 + 右侧文字」的绝对定位,坐标系不一致,
//   导致过「文字压在背景交界线上」(S3 实测)——那是两套坐标各自为政的必然结果。
//   这里统一:设备由 DeviceStage 摆放,说明区由 PaperNote 摆放,两者都相对画布,
//   间距由常量 CENTER_X / NOTE_X 单点决定。
import type {ReactNode} from 'react';

import {DeviceStage} from './DeviceStage';

/** 设备外壳中心(左侧)。 */
export const DEVICE_CX = 640;
export const DEVICE_CY = 540;

/** 右侧说明区的左边界与宽度。 */
export const NOTE_X = 1000;
export const NOTE_W = 790;

export interface ShotProps {
  /** 屏幕区内容:真实产品页面组件 */
  children: ReactNode;
  /** 相机 */
  scale?: number;
  cx?: number;
  cy?: number;
  tx?: number;
  ty?: number;
  scrollY?: number;
  deviceOpacity?: number;
  /** 右侧说明区内容 */
  note?: ReactNode;
  /** 说明区纵向起点 */
  noteTop?: number;
  /** 进入用的整体透明度 */
  opacity?: number;
}

/**
 * 渲染一个镜头:左设备 + 右说明。
 *
 * 前置: 无
 * 后置: 设备与说明区都相对画布绝对定位,互不重叠(设备右缘 ≈ 640+207=847 < 1000)
 * 异常: 无
 */
export const Shot: React.FC<ShotProps> = ({
  children,
  scale = 1,
  cx = DEVICE_CX,
  cy = DEVICE_CY,
  tx = 0,
  ty = 0,
  scrollY = 0,
  deviceOpacity = 1,
  note,
  noteTop = 240,
  opacity = 1,
}) => (
  <>
    <DeviceStage
      cx={cx}
      cy={cy}
      scale={scale}
      tx={tx}
      ty={ty}
      scrollY={scrollY}
      opacity={deviceOpacity}
    >
      {children}
    </DeviceStage>
    {note === undefined ? null : (
      <div style={{position: 'absolute', left: NOTE_X, top: noteTop, width: NOTE_W, opacity}}>
        {note}
      </div>
    )}
  </>
);

/** 说明区的眉标(小号 accent 字)——所有镜头共用同一版式。 */
export const NoteKicker: React.FC<{children: ReactNode; opacity?: number}> = ({
  children,
  opacity = 1,
}) => (
  <div
    style={{
      fontFamily: 'var(--font-body)',
      fontSize: 19,
      color: 'var(--accent)',
      letterSpacing: '0.14em',
      opacity,
    }}
  >
    {children}
  </div>
);

/** 说明区主标题。 */
export const NoteTitle: React.FC<{children: ReactNode; opacity?: number; size?: number}> = ({
  children,
  opacity = 1,
  size = 40,
}) => (
  <div
    style={{
      fontFamily: 'var(--font-display)',
      fontSize: size,
      fontWeight: 500,
      color: 'var(--fg)',
      lineHeight: 1.42,
      marginTop: 18,
      opacity,
    }}
  >
    {children}
  </div>
);

/** 说明区正文段。 */
export const NoteBody: React.FC<{children: ReactNode; opacity?: number; top?: number}> = ({
  children,
  opacity = 1,
  top = 26,
}) => (
  <div
    style={{
      fontFamily: 'var(--font-body)',
      fontSize: 22,
      color: 'var(--muted)',
      lineHeight: 1.78,
      marginTop: top,
      opacity,
    }}
  >
    {children}
  </div>
);
