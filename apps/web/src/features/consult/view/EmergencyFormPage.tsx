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

import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router';

import { ConfirmSheet } from '../../../shared/ui/ConfirmSheet';
import { AppShell } from '../../../shared/ui/AppShell';
import type { ConsultPort } from '../application/ports';
import { SKIP_SEMANTICS_COPY } from '../domain/emergency';
import { useEmergencyForm } from '../viewModel/useEmergencyForm';
import { consultChatPath } from './consultRoutes';
import styles from './emergencyFormPage.module.css';
// 选择卡（.selection/.check-box）与进度条（.progress-track）的契约规则在本表里，
// 不 import 就只剩浏览器默认外观（原生 radio 可见、进度条 0px）。
import './consultComponents.css';

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
  const location = useLocation();
  const [confirmExit, setConfirmExit] = useState(false);
  const form = useEmergencyForm(consult, (sessionId) => {
    navigate(consultChatPath(sessionId));
  });

  const { current } = form;
  const exit = (): void => {
    const state: unknown = location.state;
    const returnTo = typeof state === 'object' && state !== null && 'returnTo' in state && typeof state.returnTo === 'string'
      && state.returnTo.startsWith('/') && !state.returnTo.startsWith('//') ? state.returnTo : '/';
    void navigate(returnTo);
  };

  return (
    <AppShell className={styles.shell}>
      <header className="subpage-head">
        <button type="button" className="sp-back text-button" disabled={form.submitting} onClick={() => form.handled > 0 ? setConfirmExit(true) : exit()}>
          ← 退出应急
        </button>
        <span className="sp-title">现在的情况</span>
      </header>

      <p className={styles.skipNote}>{SKIP_SEMANTICS_COPY}</p>

      <section className="tile" aria-labelledby="emergency-step-title" inert={form.submitting}>
        <div className="step-meta">
          <span className="meta">
            第 {form.index + 1} / {form.total} 题
          </span>
          <button type="button" className="text-button" disabled={form.isFirst || form.submitting} onClick={form.previous}>
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

      {/*
        emergency-controls 是给 e2e 中和与截图用的稳定钩子（见 e2e/support/neutralise.ts），
        产品侧的实际定位由 styles.controls 提供——它是 fixed，长图截图前必须被中和成 static，
        因此这个类名不能删，也不要指望在 src 下找到它的规则：契约 components.html 里同名规则
        只作用于那张目录页自己的 .emergency-preview 试样。
      */}
      <div className={"emergency-controls " + styles.controls}>
        <div className="button-row">
          <button type="button" className="btn btn-quiet" disabled={form.submitting} onClick={() => { form.skip(); if (!form.isLast) form.next(); }}>
            跳过这题
          </button>
          <button type="button" className="btn" disabled={form.isLast || form.submitting} onClick={form.next}>
            下一题
          </button>
        </div>
        <button type="button" className="btn btn-primary block" disabled={form.submitting} onClick={() => void form.submit()}>
          {form.submitting ? '正在提交…' : '提交，开始分析'}
        </button>
        <p className="meta">随时提交，无需答完八题。</p>
      </div>
      {confirmExit && (
        <ConfirmSheet labelledBy="emergency-exit-title" onDismiss={() => setConfirmExit(false)}>
          <h2 id="emergency-exit-title">退出现场采集？</h2>
          <p>已填写的内容还没有提交，退出后将丢弃。</p>
          <div className="button-row">
            <button className="btn btn-secondary" type="button" onClick={() => setConfirmExit(false)}>继续填写</button>
            <button className="btn btn-danger" type="button" onClick={exit}>退出并丢弃</button>
          </div>
        </ConfirmSheet>
      )}
    </AppShell>
  );
}
