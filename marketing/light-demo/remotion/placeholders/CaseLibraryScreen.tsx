import {C, FONT_BODY, FONT_DISPLAY} from '../lib/tokens';
import {PageHead, Screen, TabBar} from './PhoneScreen';

// 案例库占位:内容取自 shot-list.md ⑤ 走查记录与种子数据——
// 4 案例(1 虚构样例 + 3 真实访谈),「虚构样例」与真实案例同屏可辨(AC-06)。

const CaseTag: React.FC<{fictional?: boolean}> = ({fictional = false}) => (
  <span
    style={{
      fontSize: 11,
      borderRadius: 9999,
      padding: '1px 8px',
      fontFamily: FONT_BODY,
      flexShrink: 0,
      color: fictional ? C.statusUnruled : C.statusStable,
      border: `1px solid ${fictional ? C.statusUnruled : C.statusStable}`,
    }}
  >
    {fictional ? '虚构样例' : '真实访谈'}
  </span>
);

const CaseRow: React.FC<{title: string; source: string; fictional?: boolean}> = ({
  title,
  source,
  fictional = false,
}) => (
  <div
    style={{
      backgroundColor: C.surface,
      border: `1px solid ${C.borderSoft}`,
      borderRadius: 14,
      padding: '12px 13px',
    }}
  >
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8}}>
      <span style={{fontSize: 14, fontWeight: 600, color: C.fg, fontFamily: FONT_BODY, lineHeight: 1.4}}>
        {title}
      </span>
      <CaseTag fictional={fictional} />
    </div>
    <div style={{fontSize: 11, color: C.muted, marginTop: 7, fontFamily: FONT_BODY}}>{source}</div>
  </div>
);

export const CaseLibraryScreen: React.FC = () => (
  <Screen>
    <PageHead />
    <div style={{padding: '8px 16px 0', flex: 1, overflow: 'hidden'}}>
      <div style={{fontFamily: FONT_DISPLAY, fontSize: 20, fontWeight: 500, color: C.fg}}>
        案例库
      </div>
      <div style={{display: 'flex', flexDirection: 'column', gap: 9, marginTop: 14}}>
        <CaseRow
          title="超市里孩子突然捂耳蹲下:一次感官过载的离场"
          source="来源:演示用虚构样例"
          fictional
        />
        <CaseRow
          title="公共场所情绪崩溃后的 20 分钟:一位父亲的复盘"
          source="来源:真实访谈 2026-05"
        />
        <CaseRow
          title="成人 PDD 的社交场合应对:自我陈述整理"
          source="来源:真实访谈 2026-05"
        />
        <CaseRow
          title="从医院候诊到平静离开:环境调整清单"
          source="来源:真实访谈 2026-05"
        />
      </div>
    </div>
    <TabBar active="首页" />
  </Screen>
);
