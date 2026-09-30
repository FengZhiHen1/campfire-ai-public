/**
 * 模块: features/consult/view/MessageParts/ActionCard
 * 职责: 应急行动卡渲染——七节分区、医疗风险三值徽章、来源/置信标注与失效态
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 契约修订 4（.action-card 全部规格）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6.2 节（分派、越界拒渲染、旧卡失效）
 *   - docs/技术设计/面/consult/tools/emit_emergency_action_card.md: MUST — 第 4 节（状态词表）
 * 边界:
 *   - 依赖: features/consult/domain/actionCard（纯转换内核）、domain/parts
 *   - 被依赖: view/MessageParts/parts
 * 禁止行为:
 *   - 禁止解析模型 markdown 猜结构（只信事件载荷）
 *   - 禁止渲染取值越界的卡片（拒渲染并显式说明，不静默改写）
 *   - 禁止用裸色块表达医疗风险（必须走 .status 语义徽章，DESIGN.md 反模式）
 */

import type { ActionCardEvent } from '../../../../shared/types/sse';
import { buildActionCard, type ActionCardSectionView } from '../../domain/actionCard';

/** 行动卡 props。 */
export interface ActionCardProps {
  /** 事件载荷（通用信封）。 */
  data: ActionCardEvent;
  /** 是否已被更新的卡片取代（重复评估后的旧卡不删除，标为失效）。 */
  expired: boolean;
}

/** 一行动作 + 可选的来源标注。 */
function ActionLine({ text, annotation }: ActionCardSectionView['lines'][number]) {
  return (
    <p>
      {text}
      {annotation === null ? null : (
        <small className="ac-source">
          来源：{annotation.sourceLabel} · 置信：{annotation.confidenceLabel}
        </small>
      )}
    </p>
  );
}

/**
 * 渲染行动卡。
 *
 * 前置: data 是 action_card 事件的通用信封
 * 后置: 越界载荷输出 .error-card（拒渲染）；合法载荷按七节分区渲染，失效卡加虚线边框与过期条
 * 异常: 无
 */
export function ActionCard({ data, expired }: ActionCardProps) {
  const build = buildActionCard(data, { expired });

  if (build.status === 'rejected') {
    // 拒渲染而不是「尽量显示一部分」：取值越界的卡片看起来合法，会让人照它行动。
    return (
      <div className="error-card" role="alert">
        <strong className="ec-title">这张行动卡没有显示</strong>
        <p>
          收到的卡片内容不合要求（{build.reason}），因此没有按照它行动。请重试或换一种说法描述现场情况。
        </p>
      </div>
    );
  }

  const view = build.view;
  const priority = view.sections.find((section) => section.isPriority) ?? null;

  return (
    <article className={`panel action-card${view.expired ? ' expired' : ''}`} aria-label={`行动卡：${view.title}`}>
      <span className="tag">{view.title}</span>
      {view.expired ? <p className="status off">已过期，见最新卡片</p> : null}

      {priority !== null && !view.expired ? (
        <div className="chat-action-priority">
          <span className="meta">现在先看 · {priority.heading}</span>
          {priority.lines.map((line, index) => (
            <ActionLine key={`priority-${String(index)}`} {...line} />
          ))}
        </div>
      ) : null}

      {view.sections.map((section) => (
        <div className={`ac-section${section.isPriority ? ' now' : ''}`} key={section.key}>
          <h3 className="ac-head">
            <span>{section.ordinal}</span>
            {section.heading}
          </h3>
          {section.key === view.medicalRiskSectionKey ? (
            <>
              <p>
                <span className={`status ${view.medicalRisk.tone}`}>{view.medicalRisk.text}</span>
              </p>
              {view.stateLines.map((line) => (
                <p key={line}>{line}</p>
              ))}
            </>
          ) : null}
          {section.lines.map((line, index) => (
            <ActionLine key={`${section.key}-${String(index)}`} {...line} />
          ))}
        </div>
      ))}
    </article>
  );
}
