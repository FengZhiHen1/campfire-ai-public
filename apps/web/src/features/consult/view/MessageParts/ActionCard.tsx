/**
 * 模块: features/consult/view/MessageParts/ActionCard
 * 职责: 应急行动卡渲染——七节分区、医疗风险三值徽章、来源/置信标注与失效态
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 契约修订 4（.action-card 全部规格）
 *   - docs/design/pages/应急表单页.md: MUST — 「最新行动卡及其医疗风险和来源保持可辨」
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6.2 节（分派、越界拒渲染、旧卡失效）
 *   - docs/技术设计/面/consult/tools/emit_emergency_action_card.md: MUST — 第 4 节（状态词表）
 * 边界:
 *   - 依赖: features/consult/domain/actionCard（纯转换内核）、domain/parts
 *   - 被依赖: view/MessageParts/parts
 * 禁止行为:
 *   - 禁止解析模型 markdown 猜结构（只信事件载荷）
 *   - 禁止渲染取值越界的卡片（拒渲染并显式说明，不静默改写）
 *   - 禁止用裸色块表达医疗风险（必须走 .status 语义徽章，DESIGN.md 反模式）
 *   - 禁止把医疗风险压到「立即做」之后（高风险优先是原业务语义，视觉重做不得调序）
 */

import type { ActionCardEvent } from '../../../../shared/types/sse';
import { buildActionCard, type ActionCardSectionView } from '../../domain/actionCard';
import styles from './actionCard.module.css';
// 医疗风险三值徽章的形态与颜色来自全局契约表 `.status.stable/.unruled/.high`
// （DESIGN.md：不得用裸色块表达医疗风险）。本页自己的布局/排版/来源标注写在本地 module 里。
import '../../../../shared/styles/components.css';

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
    <p className={styles.line}>
      <span className={styles.lineText}>{text}</span>
      {annotation === null ? null : (
        <small className={`ac-source ${styles.source}`}>
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
 *
 * 2026-11-18 本轮（角色化重做）：
 *   - 医疗风险与「立即做」是这张卡的头两条读信息，风险徽章固定在标题行、永远在最前；
 *   - 当前卡将「立即做」作为卡首的暖底分节，旧卡仍按原顺序展示全部内容；
 *   - 失效态不再只是一条灰色虚边：标题降权、整卡压成「历史」的纸色，并保留全部内容。
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
  const priority = view.expired ? undefined : view.sections.find((section) => section.isPriority);
  const sections = priority === undefined
    ? view.sections
    : [priority, ...view.sections.filter((section) => section !== priority)];
  // 医疗风险优先于行动建议：徽章放在卡标题行，保证「风险状态」早于「立即做」推荐块出现。
  const riskFirst = view.medicalRisk;

  return (
    <article
      className={`panel action-card ${styles.card}${view.expired ? ` expired ${styles.expired}` : ''}`}
      aria-label={`行动卡：${view.title}`}
      data-risk={riskFirst.tone}
    >
      {/* 标题行：卡身份（行动卡标签，宋体）在最前，医疗风险徽章紧随其后——风险早于一切动作。 */}
      <div className={`ac-top ${styles.top}`}>
        <span className={styles.eyebrow}>应急行动卡</span>
        <span className={`status ${riskFirst.tone} ac-risk ${styles.risk}`}>{riskFirst.text}</span>
      </div>
      <h3 className={styles.title}>{view.title}</h3>
      {view.expired ? (
        <p className={`status off ${styles.expiredNote}`}>已过期，见最新卡片</p>
      ) : null}

      {sections.map((section) => {
        const pinned = section === priority;
        const useStateLines = section.key === view.medicalRiskSectionKey;
        return (
          <div className={`ac-section ${pinned ? `chat-action-priority ${styles.priorityBlock}` : styles.section}`} key={section.key}>
            <h4 className={`ac-head ${pinned ? styles.priorityMeta : styles.head}`}>
              {pinned ? '现在先看 · ' : <span className={styles.ordinal}>{section.ordinal}</span>}
              {section.heading}
            </h4>
            {useStateLines
              ? view.stateLines.map((line) => (
                  <p className={styles.line} key={line}>
                    <span className={styles.lineText}>{line}</span>
                  </p>
                ))
              : section.lines.map((line, index) => (
                  <ActionLine key={`${section.key}-${String(index)}`} {...line} />
                ))}
          </div>
        );
      })}
    </article>
  );
}
