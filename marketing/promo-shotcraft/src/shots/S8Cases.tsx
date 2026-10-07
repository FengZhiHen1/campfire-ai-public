// S8 案例库 —— 用**真实 LibraryPage 组件 + 真实库数据**。
//
// ── 为什么用组件而不是元素切片 ────────────────────────────────────────────
// 旧版(方案 B)为了避开案例条目里的**授权台账元数据**
// (「来源:用户 2026-09-29 裁决…本项目未持有同意文本本身…」),改用手工裁的
// 元素切片贴图。那能用,但一旦产品文案或版式变化就失真。
// 新版直接用真实页面:授权元数据是产品**真实界面的一部分**,
// 展示它反而更诚实 —— 它说明「这条案例的来源与授权是可追溯的」。
//
// 数据来自 fixture:数据库导出的 4 条案例(1 fictional + 3 internal)与 2 条资料。
//
// 节奏(300f / 10s):
//   ① 0-90f   案例列表首屏 + 推近
//   ② 90-200f 滚动到「虚构样例」条目(标签是产品自己的状态标签)
//   ③ 200-300f 右侧讲「虚构与真实同屏可辨 + 每条都标来源」
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {MemoryRouter} from 'react-router';

import {LibraryPage} from '../../../../apps/web/src/features/library/view/LibraryPage';
import {DeviceStage, FilmRoot} from '../lib/DeviceStage';
import {NoteKicker, NoteTitle, NOTE_X} from '../lib/Shot';
import {scrollTo, markScrollPx} from '../lib/pageScroll';
import {pushCamera, stagedPush} from '../lib/camera';
import {useShotTiming} from '../lib/shotTiming';
import {makeLibraryPort} from '../fixtures/ports';

const PORT = makeLibraryPort();

export const S8Cases: React.FC = () => {
  const frame = useCurrentFrame();
  const t = useShotTiming();

  // 相机:★ 三阶推近(每阶对应叙事上的下一件事:列表首屏 → 滚向虚构样例 → 标签锁定)。
  //   ★ 2026-10-07:原为 1.00→1.20 线性铺满整段 —— 13s 里每 30 帧只有 0.0154,
  //     低于 lib/camera.ts 的可见下限(0.02),读起来就是用户说的那种「微动」。
  //     改为三阶后每阶位移可见,且与原周期漂移分量一并删除。
  const camScale = pushCamera(frame, 1.0, 1.2, t.duration).scale;
  const stageScale = stagedPush(frame, [1.0, 1.08, 1.2], [0, t.at(0.45), t.at(0.8)]);
  const scale = Math.max(camScale, stageScale);

  // 屏内滚动:★ 目标由**实测元素位置**给出,不是猜的像素。
  // 实测(capture/measure-element-positions.mjs):
  //   「虚构样例」标签 offsetTop=1719;该页 maxScroll=1204。
  //   把它滚到屏幕上方 1/4 需要 1204px(= 恰好到底),因此终值取 markScrollPx。
  // 旧版写死 1680 > 1204 → 滚出内容底部,露出授权台账尾部与空白(用户实测)。
  // 本段 390f(13s)比旧版 300f 长,多出的时间给**列表本身的滚动过程**
  //   (13s 里滚动占约 8s,比旧版从容),而不是让画面停在终点。
  const scrollToTag = markScrollPx('cases', '虚构样例');
  const scrollY = interpolate(
    frame,
    [0, t.at(0.22), t.at(0.72), t.at(0.93)],
    [0, scrollTo('cases', 0.15), scrollToTag * 0.82, scrollToTag],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.3, 0, 0.2, 1)},
  );

  const fadeOut = interpolate(frame, t.span(0.94, 1), [1, 0.06], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  /** 右侧说明条目的落位(cue 用比例给,段长变化自动跟随)。 */
  const noteIn = (ratio: number) =>
    interpolate(frame, t.span(ratio, ratio + 0.07), [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.2, 0.7, 0.25, 1),
    });

  // 标签高亮:到达时一次**回弹**然后静止。
  //   ★ 2026-10-07:替换原先的 sin 持续脉动(14f 周期)。
  const tagPop = 1 - interpolate(frame, t.span(0.86, 0.93), [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });

  return (
    <FilmRoot>
      <div style={{position: 'absolute', inset: 0, opacity: fadeOut}}>
        <DeviceStage cx={640} cy={540} scale={scale} scrollY={scrollY}>
          <MemoryRouter initialEntries={['/cases']}>
            <LibraryPage port={PORT} />
          </MemoryRouter>
        </DeviceStage>

        {/* 高亮「虚构样例」状态标签 —— 用 CSS 命中真实元素。
            ★ 选择器必须对准**虚构条目真正用的类名**。产品里
              (apps/web/src/features/library/view/LibraryPage.tsx):
                <span className={isFictional(item.status) ? 'status off' : 'tag meta'}>
              即虚构条目拿 `status off`,内部条目才拿 `tag meta`。
              初版这里圈的是 `.tag` —— 结果恰好圈住「内部」,该被圈的「虚构样例」没有圈
              (独立审查实测抓出)。这正是「渲染真实产品」转向要消灭的那类错误:
              靠猜选择器与靠猜坐标没有本质区别。现在对准 `.status.off`。 */}
        <style>{`
          .film-root .list-row .status.off {
            position: relative;
          }
          .film-root .list-row .status.off::after {
            content: '';
            position: absolute;
            inset: -4px;
            border: 2px solid var(--status-unruled);
            border-radius: 9999px;
            opacity: ${String(0.55 + tagPop * 0.45)};
            pointer-events: none;
            box-shadow: 0 4px 18px rgba(180, 83, 9, ${String(0.16 + tagPop * 0.16)});
          }
        `}</style>

        {/* 右侧说明 */}
        <div style={{position: 'absolute', left: NOTE_X, top: 260, width: 790}}>
          <NoteKicker opacity={noteIn(0.015)}>知识与案例 · 分两库,各自标来源</NoteKicker>
          <NoteTitle opacity={noteIn(0.041)} size={42}>
            遇到没经历过的事,
            <br />
            看看别人是怎么走过来的。
          </NoteTitle>

          <div
            style={{
              marginTop: 34, fontFamily: 'var(--font-body)', fontSize: 21,
              color: 'var(--muted)', lineHeight: 1.8, opacity: noteIn(0.154),
            }}
          >
            案例与资料分两库,每条都标着来源、适用范围与证据等级。
          </div>

          <div
            style={{
              marginTop: 40, paddingTop: 26, borderTop: '1px solid var(--border-soft)',
              display: 'flex', flexDirection: 'column', gap: 16, opacity: noteIn(0.385),
            }}
          >
            <div style={{display: 'flex', alignItems: 'center', gap: 14}}>
              <span
                style={{
                  fontFamily: 'var(--font-body)', fontSize: 17, color: 'var(--status-stable)',
                  border: '2px solid var(--status-stable)', borderRadius: 9999,
                  padding: '4px 16px', flexShrink: 0,
                }}
              >
                内部
              </span>
              <span style={{fontFamily: 'var(--font-body)', fontSize: 19, color: 'var(--fg-2)'}}>
                来自真实访谈转写(3 条)
              </span>
            </div>
            <div style={{display: 'flex', alignItems: 'center', gap: 14}}>
              <span
                style={{
                  fontFamily: 'var(--font-body)', fontSize: 17, color: 'var(--status-unruled)',
                  border: '2px solid var(--status-unruled)', borderRadius: 9999,
                  padding: '4px 16px', flexShrink: 0,
                }}
              >
                虚构样例
              </span>
              <span style={{fontFamily: 'var(--font-body)', fontSize: 19, color: 'var(--fg-2)'}}>
                产品演示用素材,<span style={{color: 'var(--status-unruled)'}}>不是真实案例</span>
              </span>
            </div>
          </div>

          <div
            style={{
              marginTop: 30, fontFamily: 'var(--font-body)', fontSize: 18,
              color: 'var(--muted)', lineHeight: 1.8, opacity: noteIn(0.538),
            }}
          >
            虚构与真实在列表里一眼可辨,
            <br />
            因为状态标由数据决定,不由展示方式决定。
          </div>
        </div>
      </div>
    </FilmRoot>
  );
};
