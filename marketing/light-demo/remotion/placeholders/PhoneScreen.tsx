import {C, FONT_BODY, FONT_DISPLAY} from '../lib/tokens';
import {BrandMark, FlameDot} from '../lib/brand';

// 占位屏通用骨架:按 docs/design/pages 各页设计稿的风格化近似,
// 只用于 Playwright 真实录屏到位前验证时间线与构图,不作为成片内容。
// 文案均取自页面设计文档或走查记录,不虚构功能。

export const TabBar: React.FC<{active: '首页' | '咨询' | '档案' | '我的'}> = ({active}) => (
  <div
    style={{
      position: 'absolute',
      left: 0,
      right: 0,
      bottom: 0,
      height: 56,
      borderTop: `1px solid ${C.border}`,
      backgroundColor: C.surface,
      display: 'flex',
      fontFamily: FONT_BODY,
    }}
  >
    {(['首页', '咨询', '档案', '我的'] as const).map((t) => (
      <div
        key={t}
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          gap: 3,
          color: t === active ? C.accent : C.fg2,
          fontSize: 12,
        }}
      >
        <div
          style={{
            width: 18,
            height: 18,
            borderRadius: 5,
            border: `1.6px solid currentColor`,
          }}
        />
        {t}
      </div>
    ))}
  </div>
);

export const SubpageHead: React.FC<{back: string}> = ({back}) => (
  <div
    style={{
      height: 52,
      display: 'flex',
      alignItems: 'center',
      padding: '0 16px',
      borderBottom: `1px solid ${C.borderSoft}`,
      fontFamily: FONT_BODY,
      fontSize: 15,
      color: C.fg2,
      flexShrink: 0,
    }}
  >
    ← {back}
  </div>
);

export const ProgressTrack: React.FC<{ratio: number}> = ({ratio}) => (
  <div style={{height: 2, backgroundColor: C.border, width: '100%'}}>
    <div
      style={{height: '100%', width: `${ratio * 100}%`, backgroundColor: C.accent}}
    />
  </div>
);

// 三选一选择卡(.tile.choice):选中态 = accent 描边 + 浅 tint + 对勾
export const ChoiceTile: React.FC<{label: string; selected?: boolean}> = ({
  label,
  selected = false,
}) => (
  <div
    style={{
      minHeight: 48,
      borderRadius: 16,
      border: `1.5px solid ${selected ? C.accent : C.border}`,
      backgroundColor: selected ? 'rgba(194, 65, 12, 0.06)' : C.surface,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 16px',
      fontSize: 16,
      color: C.fg,
      fontFamily: FONT_BODY,
    }}
  >
    {label}
    {selected ? <span style={{color: C.accent, fontSize: 18}}>✓</span> : null}
  </div>
);

// 多项勾选行(.check-row)
export const CheckRow: React.FC<{label: string; checked?: boolean}> = ({
  label,
  checked = false,
}) => (
  <div
    style={{
      minHeight: 48,
      display: 'flex',
      alignItems: 'center',
      gap: 12,
      fontSize: 16,
      color: C.fg,
      fontFamily: FONT_BODY,
    }}
  >
    <div
      style={{
        width: 20,
        height: 20,
        borderRadius: 6,
        border: `1.5px solid ${checked ? C.accent : C.border}`,
        backgroundColor: checked ? C.accent : 'transparent',
        color: C.accentOn,
        fontSize: 13,
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        flexShrink: 0,
      }}
    >
      {checked ? '✓' : ''}
    </div>
    {label}
  </div>
);

export const PrimaryButton: React.FC<{label: string}> = ({label}) => (
  <div
    style={{
      minHeight: 48,
      borderRadius: 16,
      backgroundColor: C.accent,
      color: C.accentOn,
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      fontSize: 16,
      fontWeight: 600,
      fontFamily: FONT_BODY,
    }}
  >
    {label}
  </div>
);

export const QuietButton: React.FC<{label: string}> = ({label}) => (
  <div
    style={{
      minHeight: 48,
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      fontSize: 15,
      color: C.fg2,
      fontFamily: FONT_BODY,
    }}
  >
    {label}
  </div>
);

export const ScreenTitle: React.FC<{
  title: string;
  hint?: string;
  withFlame?: boolean;
  frame?: number;
}> = ({title, hint, withFlame = false, frame = 0}) => (
  <div style={{padding: '18px 20px 0', flexShrink: 0}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
      {withFlame ? <FlameDot frame={frame} size={12} /> : null}
      <span
        style={{
          fontFamily: FONT_DISPLAY,
          fontSize: 26,
          fontWeight: 500,
          color: C.fg,
        }}
      >
        {title}
      </span>
    </div>
    {hint ? (
      <div style={{fontSize: 13, color: C.muted, marginTop: 8, fontFamily: FONT_BODY}}>
        {hint}
      </div>
    ) : null}
  </div>
);

export const PageHead: React.FC = () => (
  <div
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '18px 20px 6px',
      flexShrink: 0,
    }}
  >
    <BrandMark size={26} />
    <span
      style={{fontFamily: FONT_DISPLAY, fontSize: 26, fontWeight: 500, color: C.fg}}
    >
      篝火智答
    </span>
  </div>
);

export const Screen: React.FC<{children: React.ReactNode}> = ({children}) => (
  <div
    style={{
      width: '100%',
      height: '100%',
      backgroundColor: C.bg,
      display: 'flex',
      flexDirection: 'column',
      position: 'relative',
      fontFamily: FONT_BODY,
    }}
  >
    {children}
  </div>
);
