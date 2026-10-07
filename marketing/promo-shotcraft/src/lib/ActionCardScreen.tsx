// ActionCardScreen —— 用**真实 ActionCard 组件**渲染真实行动卡数据。
//
// ── 为什么能直接用 ActionCard ─────────────────────────────────────────────
// ActionCard 是纯展示组件(props: data + expired),不依赖 runtime/store
// —— 见 apps/web/src/features/consult/view/MessageParts/ActionCard.tsx。
// 它唯一的上下文依赖来自 parts.tsx 的 ActionCardPart(取 newestActionCardId),
// 这里直接给 expired=false,不需要 provider。
//
// 因此「来源:历史记录 · 置信:已确认」这类标注由产品自己的
// domain/actionCard.ts 的映射产生 —— 影片不可能写错来源枚举(那正是上次的缺陷)。
import type {ActionCardEvent} from '../../../../apps/web/src/shared/types/sse';
import {ActionCard} from '../../../../apps/web/src/features/consult/view/MessageParts/ActionCard';
import {DeviceFrame} from '../../../../apps/web/src/shared/ui/DeviceFrame';

export interface ActionCardScreenProps {
  /** 真实卡片载荷(来自 fixture:数据库导出的 emit_emergency_action_card 参数) */
  data: ActionCardEvent;
  /** 是否显示为已过期(旧卡) */
  expired?: boolean;
  /** 屏内滚动量 */
  scrollHint?: number;
}

/**
 * 渲染行动卡屏。
 *
 * 前置: data 是真实的 action_card 事件载荷
 * 后置: 输出与产品对话页一致的卡片(七节分区 + 来源标注 + 三值徽章)
 * 异常: 无(越界载荷由 ActionCard 自己拒渲染为 error-card)
 */
export const ActionCardScreen: React.FC<ActionCardScreenProps> = ({
  data,
  expired = false,
}) => (
  // 卡片在对话流里出现 → 用与对话页相同的外壳
  <DeviceFrame>
    <div className="film-chat-thread" style={{paddingTop: 'var(--space-4)'}}>
      <ActionCard data={data} expired={expired} />
    </div>
  </DeviceFrame>
);
