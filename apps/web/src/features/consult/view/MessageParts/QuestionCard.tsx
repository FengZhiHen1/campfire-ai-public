/**
 * 模块: features/consult/view/MessageParts/QuestionCard
 * 职责: 统一提问卡渲染——单题是多题组件的 1/1 状态，三通道逐题作答、整组统一提交
 * 数据来源:
 *   - docs/design/pages/对话页.md: MUST — 契约修订 3（.question-card 全部规格与已提交态）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6.1 节（三条通道、切换保留、整组提交、已提交只读）
 * 边界:
 *   - 依赖: viewModel 的 QuestionBatchController 契约、domain/questionBatch 的类型
 *   - 被依赖: view/MessageParts/parts
 * 禁止行为:
 *   - 禁止预选答案（事实类问题不预选、不推荐）
 *   - 禁止逐题发送（只有整组提交，submit 由控制器把关）
 *   - 禁止把「跳过」写成模糊措辞（记录里显式写「（跳过）」）
 */

import { useState } from 'react';

import type { QuestionBatchController } from '../../viewModel/useQuestionBatch';

/** 提问卡 props。 */
export interface QuestionCardProps {
  controller: QuestionBatchController;
}

/**
 * 渲染提问卡。
 *
 * 前置: controller.items 非空
 * 后置: 待作答态渲染题干、编号选项、自由回答入口与整组操作；已提交/历史态渲染静态记录
 * 异常: 无
 *
 * 局部状态（收起、自由回答展开、草稿文本的开关）归 view；作答草稿归 viewModel 的 store，
 * 这样「未提交即发送其他消息」时旧卡仍保留自己的草稿（对话页设计契约修订 3）。
 */
export function QuestionCard({ controller }: QuestionCardProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [freeOpen, setFreeOpen] = useState(false);

  const current = controller.items[controller.index];
  if (current === undefined) {
    return (
      <div className="tile question-card">
        <p className="hint">这一组提问没有可显示的题目。</p>
      </div>
    );
  }

  const selectedLabel = controller.answered.kind === 'option' ? controller.answered.label : null;
  const freeText = controller.answered.kind === 'free' ? controller.answered.text : '';
  const isSkipped = controller.answered.kind === 'skip';

  return (
    <div className={`tile question-card${controller.submitted ? ' answered' : ''}`}>
      <div className="question-head">
        <span className="meta">{controller.submitted ? '已提交' : '下一步'}</span>
        {controller.submitted ? null : (
          <button
            type="button"
            className="text-button"
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((value) => !value)}
          >
            {collapsed ? '展开' : '收起'}
          </button>
        )}
      </div>

      <h3 className="q-title">{current.prompt}</h3>

      {controller.submitted ? (
        <div className="question-body" data-question-record>
          <p className="hint">
            {controller.mode === 'record'
              ? '这组问题已经处理过，记录如下（回答见当时的对话）。'
              : '整组已提交，不能再修改。'}
          </p>
          <ol className="question-record-list">
            {controller.records.map((record) => (
              <li key={record.prompt}>
                <p>{record.prompt}</p>
                <span className="meta">{record.answer === null ? '（回答见下一条消息）' : record.answer}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {!controller.submitted && !collapsed ? (
        <div className="question-body">
          <p className="hint">选择一项，或用自己的话回答；全部处理后再提交。</p>

          <div className="q-options" role="group" aria-label="选项">
            {current.options.map((option, index) => (
              <button
                type="button"
                className="question-option"
                key={option.label}
                aria-pressed={selectedLabel === option.label}
                onClick={() => controller.select(option.label)}
              >
                <span className="question-number" aria-hidden="true">
                  {index + 1}
                </span>
                <span className="question-copy">
                  <span className="question-label">{option.label}</span>
                  {option.description === undefined ? null : (
                    <span className="question-description">{option.description}</span>
                  )}
                </span>
              </button>
            ))}
          </div>

          <button
            type="button"
            className="text-button question-free-toggle"
            aria-expanded={freeOpen}
            onClick={() => setFreeOpen((value) => !value)}
          >
            <span className="question-number" aria-hidden="true">
              ＋
            </span>
            <span>用自己的话回答</span>
          </button>
          {freeOpen ? (
            <div className="field">
              <label htmlFor={`question-free-${controller.mode}-${current.id}`}>你的回答</label>
              <textarea
                id={`question-free-${controller.mode}-${current.id}`}
                value={freeText}
                onChange={(event) => controller.setFreeText(event.target.value)}
                placeholder="也可以提出其他方向……"
              />
            </div>
          ) : null}

          <div className="question-footer">
            <div className="question-progress">
              <span>
                第 {controller.index + 1} / {controller.total} 题
              </span>
              <span>
                已处理 {controller.handled} / {controller.total}
                {isSkipped ? ' · 本题已跳过（未排除）' : ''}
              </span>
            </div>
            <div className="question-actions">
              <button className="btn" type="button" disabled={controller.isFirst} onClick={controller.previous}>
                上一题
              </button>
              <button
                className="btn btn-quiet"
                type="button"
                disabled={!current.allow_skip}
                onClick={controller.skip}
              >
                跳过
              </button>
              {controller.isLast ? (
                <button
                  className="btn btn-primary"
                  type="button"
                  data-question-submit
                  disabled={!controller.complete}
                  onClick={controller.submit}
                >
                  提交
                </button>
              ) : (
                <button className="btn btn-primary" type="button" data-question-next onClick={controller.next}>
                  下一题
                </button>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
