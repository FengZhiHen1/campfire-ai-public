/**
 * 模块: features/consult/view/EmergencyFormPage
 * 职责: 应急表单页——八项一屏一题的分步流、进度条、随时提交与失败保留
 * 数据来源:
 *   - docs/design/pages/应急表单页.md: MUST — 全文（布局结构、组件选用、数据与文案、状态覆盖、动效意图）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6 节（提交后 navigate，表单页即弃）
 * 边界:
 *   - 依赖: shared/ui（AppShell）、viewModel/useEmergencyForm、domain/emergency
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止把八项做成一页长表单（页面设计布局结构第 2 节）
 *   - 禁止显示进度百分比数字（位置感足够）
 *   - 禁止弱化跳过语义文案（RQ-EMG-01 原文，不得写成「暂时跳过」）
 */

import { useNavigate } from 'react-router';

import { AppShell } from '../../../shared/ui/AppShell';
import type { ConsultPort } from '../application/ports';
import { SKIP_SEMANTICS_COPY } from '../domain/emergency';
import { useEmergencyForm } from '../viewModel/useEmergencyForm';
import { consultChatPath, CONSULT_LIST_PATH } from './consultRoutes';
import styles from './emergencyFormPage.module.css';

/** 应急表单页 props。 */
export interface EmergencyFormPageProps {
  consult: ConsultPort;
}

/**
 * 渲染应急表单页。
 *
 * 前置: 无（八项是本地结构，不请求远端）
 * 后置: 输出分步题面、进度条、跳过/下一题与常驻提交；提交成功后跳转对话页
 * 异常: 无（提交失败呈现在按钮上方，已填内容保留）
 */
export function EmergencyFormPage({ consult }: EmergencyFormPageProps) {
  const navigate = useNavigate();
  const form = useEmergencyForm(consult, (sessionId) => {
    navigate(consultChatPath(sessionId));
  });

  const { current } = form;

  return (
    <AppShell>
      <header className="subpage-head">
        <button type="button" className="sp-back text-button" onClick={() => navigate(CONSULT_LIST_PATH)}>
          ← 退出应急
        </button>
        <span className="sp-title">现在的情况</span>
      </header>

      <p className={styles.skipNote}>{SKIP_SEMANTICS_COPY}</p>

      <section className="tile" aria-labelledby="emergency-step-title">
        <div className="step-meta">
          <span className="meta">
            第 {form.index + 1} / {form.total} 题
          </span>
          <button type="button" className="text-button" disabled={form.isFirst} onClick={form.previous}>
            上一题
          </button>
        </div>

        <div
          className="progress-track"
          role="progressbar"
          aria-label="采集题目位置"
          aria-valuemin={1}
          aria-valuemax={form.total}
          aria-valuenow={form.index + 1}
        >
          <div className="progress-fill" style={{ width: `${String(form.progressRatio * 100)}%` }} />
        </div>

        {/* 方向性滑动：240ms，前进向左、回退向右（页面设计动效意图）。 */}
        <div className={form.direction === 'forward' ? styles.stepForward : styles.stepBack} key={current.key}>
          <h2 className="step-title" id="emergency-step-title" tabIndex={-1}>
            {current.prompt}
          </h2>
          <p className="hint">{current.hint}</p>

          <div className="step-options" role="group" aria-labelledby="emergency-step-title">
            {current.control === 'text' ? (
              <div className="field">
                <label htmlFor="emergency-note">刚刚发生了什么</label>
                <textarea
                  id="emergency-note"
                  value={form.answer.note}
                  onChange={(event) => form.setNote(event.target.value)}
                  placeholder="一两句话就够，写不清也可以跳过。"
                />
              </div>
            ) : (
              current.options.map((option) => {
                const checked = form.answer.selected.includes(option.value);
                return (
                  <label className="selection" key={option.value}>
                    <input
                      type={current.control === 'multi' ? 'checkbox' : 'radio'}
                      name={current.key}
                      value={option.value}
                      checked={checked}
                      onChange={() =>
                        current.control === 'multi' ? form.toggle(option.value) : form.choose(option.value)
                      }
                    />
                    <span className="check-box" aria-hidden="true" />
                    <span>{option.label}</span>
                  </label>
                );
              })
            )}
          </div>

          {current.allowNote && current.control !== 'text' ? (
            <div className="field">
              <label htmlFor="emergency-extra">补充一句（可选）</label>
              <textarea
                id="emergency-extra"
                value={form.answer.note}
                onChange={(event) => form.setNote(event.target.value)}
                placeholder="可以补一句你观察到的样子。"
              />
            </div>
          ) : null}
        </div>

        <p className={styles.handledNote}>
          已处理 {form.handled} / {form.total} 题
          {form.answer.skipped ? ' · 本题已跳过（按未排除处理）' : ''}
        </p>
      </section>

      {form.failure === null ? null : (
        <div className="error-card" role="alert">
          <strong className="ec-title">{form.failure.title}</strong>
          <p>{form.failure.message}已填内容仍在，可以直接重试。</p>
        </div>
      )}

      <div className={styles.controls}>
        <div className="button-row">
          <button type="button" className="btn btn-quiet" onClick={form.skip}>
            跳过这题
          </button>
          <button type="button" className="btn" disabled={form.isLast} onClick={form.next}>
            下一题
          </button>
        </div>
        <button type="button" className="btn btn-primary block" disabled={form.submitting} onClick={() => void form.submit()}>
          {form.submitting ? '正在提交…' : '提交，开始分析'}
        </button>
        <p className="meta">随时提交，无需答完八题。</p>
      </div>
    </AppShell>
  );
}
