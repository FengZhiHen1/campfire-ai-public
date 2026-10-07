import {useCurrentFrame} from 'remotion';
import {C, FONT_BODY, FONT_DISPLAY} from '../lib/tokens';
import {Screen, SubpageHead} from './PhoneScreen';

// 行动卡占位:内容逐项取自 shot-list.md ③-d 走查记录——
// 01-05 编号区块、医疗风险三档、「来源:AI 推断·置信」逐条标注、
// 「未采集 = 未排除」诚实标注、过程链可展开。
// 三档徽标用契约语义色 --status-stable / --status-unruled / --status-high。

const RiskBadge: React.FC<{label: string; color: string}> = ({label, color}) => (
  <span
    style={{
      fontSize: 12,
      color,
      border: `1px solid ${color}`,
      borderRadius: 9999,
      padding: '2px 9px',
      fontFamily: FONT_BODY,
      flexShrink: 0,
    }}
  >
    {label}
  </span>
);

const Block: React.FC<{
  num: string;
  title: string;
  lines: string[];
  source: string;
}> = ({num, title, lines, source}) => (
  <div
    style={{
      backgroundColor: C.surface,
      border: `1px solid ${C.borderSoft}`,
      borderRadius: 16,
      padding: '13px 14px',
    }}
  >
    <div style={{display: 'flex', gap: 10, alignItems: 'baseline'}}>
      <span style={{fontSize: 13, color: C.accent, fontWeight: 700, fontFamily: FONT_BODY}}>
        {num}
      </span>
      <span style={{fontSize: 15, fontWeight: 600, color: C.fg, fontFamily: FONT_BODY}}>
        {title}
      </span>
    </div>
    {lines.map((l) => (
      <div
        key={l}
        style={{fontSize: 13, color: C.fg2, marginTop: 7, lineHeight: 1.5, fontFamily: FONT_BODY}}
      >
        · {l}
      </div>
    ))}
    <div style={{fontSize: 11, color: C.muted, marginTop: 9, fontFamily: FONT_BODY}}>
      来源:{source}
    </div>
  </div>
);

export const ActionCardScreen: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Screen>
      <SubpageHead back="返回首页" />
      <div style={{padding: '14px 16px 0', flex: 1, overflow: 'hidden'}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
          <span style={{fontFamily: FONT_DISPLAY, fontSize: 21, fontWeight: 500, color: C.fg}}>
            现场行动建议
          </span>
        </div>

        {/* 医疗风险三档,走查确认是结果页最上方的显著标注 */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginTop: 12,
            padding: '10px 12px',
            borderRadius: 12,
            backgroundColor: C.surface,
            border: `1px solid ${C.borderSoft}`,
          }}
        >
          <span style={{fontSize: 12, color: C.fg2, fontFamily: FONT_BODY}}>医疗风险</span>
          <RiskBadge label="稳定" color={C.statusStable} />
          <RiskBadge label="未排除" color={C.statusUnruled} />
          <RiskBadge label="高风险" color={C.statusHigh} />
        </div>

        <div style={{display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12}}>
          <Block
            num="01"
            title="现在先这样说"
            lines={['语速放慢,句子变短', '先叫名字,再说一件具体的事']}
            source="小满档案 · 监护人观察"
          />
          <Block
            num="02"
            title="怎么离开现场"
            lines={['从侧门离场,避开收银排队区', '带到安静角落,给 5-10 分钟']}
            source="AI 推断 · 置信:中"
          />
          <Block
            num="03"
            title="如果情况升级"
            lines={['就近服务台广播寻人/协助', '家长群内有经验的照护者']}
            source="案例 · 虚构样例(超市场景)"
          />
        </div>

        {/* 诚实标注 + 过程链,走查确认 UI 直接可见 */}
        <div
          style={{
            marginTop: 12,
            fontSize: 11,
            color: C.muted,
            lineHeight: 1.6,
            fontFamily: FONT_BODY,
          }}
        >
          未采集的项按「未排除」处理,不会当作正常
        </div>
        <div
          style={{
            marginTop: 6,
            fontSize: 12,
            color: C.fg2,
            fontFamily: FONT_BODY,
          }}
        >
          ▸ 查看分析过程(查阅资料 ×2 · 案例 ×1)
        </div>
      </div>
    </Screen>
  );
};
