import {C, PHONE} from '../lib/tokens';

// 构图 A 手机设备框:暖墨外壳 + 暖白屏幕,屏幕内容(占位屏或真实录屏)作为 children。
// 布局常量取自 lib/tokens.ts 的 PHONE,与 LayoutPreview 验证过的构图一致。
// focusX/focusY 是屏幕内对焦点的百分比(0-100),scale 放大时变换原点落在该点,
// 使 zoom 后目标区域保持居中,不需要手工换算位移。
export const PhoneFrame: React.FC<{
  children: React.ReactNode;
  scale?: number;
  translateX?: number;
  focusX?: number;
  focusY?: number;
}> = ({children, scale = 1, translateX = 0, focusX = 50, focusY = 50}) => (
  <div
    style={{
      position: 'absolute',
      left: PHONE.cx - PHONE.w / 2,
      top: PHONE.cy - PHONE.h / 2,
      width: PHONE.w,
      height: PHONE.h,
      borderRadius: 56,
      backgroundColor: C.fg,
      padding: 14,
      transform: `translateX(${translateX}px) scale(${scale})`,
      transformOrigin: `${focusX}% ${focusY}%`,
      boxShadow: '0 40px 80px rgba(32, 25, 20, 0.25)',
    }}
  >
    <div
      style={{
        width: '100%',
        height: '100%',
        borderRadius: 44,
        backgroundColor: C.surface,
        overflow: 'hidden',
      }}
    >
      {children}
    </div>
  </div>
);
