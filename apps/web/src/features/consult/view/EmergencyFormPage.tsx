/**
 * 模块: features/consult/view/EmergencyFormPage
 * 职责: 应急表单页——八项一屏一题的分步流，进度/当前问题/安全文案一眼可读，随时提交与失败保留
 * 数据来源:
 *   - docs/design/pages/应急表单页.md: MUST — 全文（布局结构、组件选用、数据与文案、状态覆盖、动效意图）
 *   - docs/技术设计/technical-details/咨询对话界面.md: MUST — 第 6 节（提交后 navigate，表单页即弃）
 *   - docs/需求/功能需求与验收.md: MUST — RQ-EMG-01（八项可跳过，跳过 = 未排除）
 * 边界:
 *   - 依赖: shared/ui（AppShell、BackChevron、ConfirmSheet）、viewModel/useEmergencyForm、domain/emergency、
 *           view/emergency（EmergencyProgress / EmergencyQuestionStep / EmergencyBackStep / EmergencySubmitDock）
 *   - 被依赖: app/routes
 * 禁止行为:
 *   - 禁止把八项做成一页长表单（页面设计布局结构第 2 节）
 *   - 禁止显示进度百分比数字（位置感足够）
 *   - 禁止弱化跳过语义文案（RQ-EMG-01 原文，不得写成「暂时跳过」）
 *   - 禁止删掉 emergency-controls 钩子（e2e 中和 fixed 用）
 *   - 禁止把 `progress-track` 字面类名改掉（e2e 截图按它取位置量）
 */

import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router';

import { AppShell } from '../../../shared/ui/AppShell';
import { BackChevron } from '../../../shared/ui/BackLink';
import { ConfirmSheet } from '../../../shared/ui/ConfirmSheet';
import { safeReturnTo } from '../../../shared/ui/returnTo';
import type { ConsultPort } from '../application/ports';
import { SKIP_SEMANTICS_COPY } from '../domain/emergency';
import { useEmergencyForm } from '../viewModel/useEmergencyForm';
import { useRunStore } from '../viewModel/runStore';
import { consultChatPath } from './consultRoutes';
import { EmergencyProgress } from './emergency/EmergencyProgress';
import { EmergencyBackStep } from './emergency/EmergencyBackStep';
import { EmergencyQuestionStep } from './emergency/EmergencyQuestionStep';
import { EmergencySubmitDock } from './emergency/EmergencySubmitDock';
import styles from './emergency/emergencyForm.module.css';
// 只在「退出确认单」里用到的契约基元（.btn/.button-row）由全局组件表提供，本页不再
// import consultComponents.css：分步流自己把选中/按压/当前题等都画在 emergencyForm.module.css 里，
// 进度条也不再消费契约 `.progress-track` 的 2px 细条规则（见该表顶部说明）。
import '../../../shared/styles/components.css';

/** 应急表单页 props。 */
export interface EmergencyFormPageProps {
  consult: ConsultPort;
}

/**
 * 渲染应急表单页。
 *
 * 前置: 无（八项是本地结构，不请求远端）
 * 后置: 输出安全文案、分段进度、当前问题与选项、推进栏与常驻提交区；提交成功后跳转对话页
 * 异常: 无（提交失败呈现在提交区上方，已填内容保留，可重试）
 */
export function EmergencyFormPage({ consult }: EmergencyFormPageProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const form = useEmergencyForm(consult, (sessionId, runId) => {
    // 运行已在应急入口启动：把 run_id 交到对话页，由它订阅（HTTP/SSE 契约第 5 节
    //「前端拿 run_id 直接跳对话页订阅」）。此前只传 sessionId，页面于是从不订阅本次运行，
    // 运行期间的输出与行动卡一律不显示——必须手动刷新才看得到。
    useRunStore.getState().setPendingAttachedRun(sessionId, runId);
    navigate(consultChatPath(sessionId));
  });

  const { current } = form;
  const exit = (): void => {
    // 返回地址只经这一处判断（与返回链接同一份）：退出应急回到实际来源，判不出来时回首页。
    void navigate(safeReturnTo(location.state) ?? '/');
  };

  // 退出经控制器判定：有已处理内容时先弹确认单，没有则直接回到来源。
  const handleExit = (): void => {
    if (form.requestExit() === 'leave') exit();
  };

  // 题间切换后把焦点移到新题干，读屏与键盘用户立即听到/看到「当前问题」。
  useEffect(() => {
    document.getElementById('emergency-step-title')?.focus({ preventScroll: true });
    // 依赖故意只取 index：题干节点按题 key 重建，题号一变就要重新聚焦；规则把
    // 「effect 体不读 index、只在 deps 里用」判成多余依赖，这里豁免一次（属于有意为之）。
    // oxlint-disable-next-line react/exhaustive-effect-dependencies
  }, [form.index]);

  return (
    <AppShell className={styles.shell}>
      <header className="subpage-head">
        {/*
          退出键与其它次级页共用同一个返回字形（shared/ui 的 BackChevron），文字保留「退出应急」：
          这一页的退出不是「返回」，而是会丢弃现场采集的决定——文字语义不能改，只借字形。
          它是 button 而不是 BackLink：退出要先经控制器判定（有已填内容要弹确认单），不能让一个
          <a> 直接导航走。字形 + .sp-back 的形态由契约表提供，本页只保证它和返回键长得一致。
        */}
        <button
          type="button"
          className={`sp-back text-button ${styles.exitButton}`}
          disabled={form.submitting}
          onClick={handleExit}
        >
          <BackChevron />
          退出应急
        </button>
        <span className="sp-title">现在的情况</span>
      </header>

      {/* 安全文案：跳过 = 未排除，是 RQ-EMG-01 最容易被无声违反的一处，放在最上。 */}
      <p className={styles.skipBanner}>
        <span className={styles.skipBannerMark} aria-hidden="true" />
        {SKIP_SEMANTICS_COPY}
      </p>

      <EmergencyProgress steps={form.steps} index={form.index} currentSkipped={form.currentStatus === 'skipped'} />

      <section
        className={styles.panel}
        aria-labelledby="emergency-step-title"
        aria-busy={form.submitting}
      >
        <EmergencyBackStep isFirst={form.isFirst} disabled={form.submitting} onPrevious={form.previous} />

        {/*
          key = current.key：换题时这一层整体重建，方向性滑动才会真的播一次。
          提交中给这一层挂 inert（与 aria-busy 同时）：题面与选项不能改，视觉上用 .stepLocked
          把它压成「按下去了、先等结果」的样子。
        */}
        <div
          className={
            (form.direction === 'forward' ? styles.stepForward : styles.stepBack) +
            (form.submitting ? ` ${styles.stepLocked}` : '')
          }
          key={current.key}
          inert={form.submitting ? true : undefined}
        >
          <EmergencyQuestionStep
            question={current}
            answer={form.answer}
            onToggle={form.toggle}
            onChoose={form.choose}
            onNote={form.setNote}
            disabled={form.submitting}
          />
        </div>
      </section>

      {form.failure === null ? null : (
        <div className={styles.failure} role="alert">
          <strong className={styles.failureTitle}>{form.failure.title}</strong>
          <p className={styles.failureBody}>{form.failure.message}已填内容仍在，可以直接重试。</p>
          <button type="button" className={styles.failureRetry} disabled={form.submitting} onClick={() => void form.submit()}>
            重试
          </button>
        </div>
      )}

      {/*
        emergency-controls 是给 e2e 中和与截图用的稳定钩子（见 e2e/support/neutralise.ts），
        产品侧的实际定位由 styles.controls 提供（fixed），长图截图前必须被中和成 static。
        这个类名不能删，也不要指望在 src 下找到它的规则：契约 components.html 里同名规则
        只作用于那张目录页自己的 .emergency-preview 试样。
      */}
      <div className={"emergency-controls " + styles.controls}>
        <EmergencySubmitDock
          isLast={form.isLast}
          submitting={form.submitting}
          onSkip={form.skip}
          onNext={form.next}
          onSubmit={() => void form.submit()}
        />
      </div>

      {form.exitConfirmOpen && (
        <ConfirmSheet labelledBy="emergency-exit-title" onDismiss={form.cancelExit}>
          <h2 id="emergency-exit-title">退出现场采集？</h2>
          <p>已填写的内容还没有提交，退出后将丢弃。</p>
          <div className="button-row">
            <button className="btn btn-secondary" type="button" onClick={form.cancelExit}>继续填写</button>
            <button
              className="btn btn-danger"
              type="button"
              onClick={() => {
                form.confirmDiscard();
                exit();
              }}
            >
              退出并丢弃
            </button>
          </div>
        </ConfirmSheet>
      )}
    </AppShell>
  );
}
