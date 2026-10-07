"""语义事件度量 —— **诊断记录,不是关卡**。

★★ 2026-10-07 用户裁决:**不以运动量设门**。本脚本因此**退休为诊断工具**:
  · 四项度量**照测**(数据是真的、帧号是准的),但**不再以非零退出码表示「不合格」**;
  · 用途改为:需要知道「哪一段没有事件」时,给出可定位的帧号。
  · 需要重新把它当关卡时,把文件末尾的注释块按说明恢复即可。

下面是这套度量的由来与口径,**保留完整**以免后来者重造一遍:

原始动机:「任意窗口都要有像素变化」那把尺子把度量写成了目标 ——
拍摄侧为了通过它,给整机叠了一段 **sin/cos 周期漂移**(±10~14px,约 1.1s 一圈)。
用户的判词是「非常反人类」「没有任何语义」「还会影响表现效果」。
那是**为指标而造的运动**,不是叙事需要的运动(与 P0「清单失明」同型:
度量一旦变成目标,就会长出迎合它的东西)。漂移已删除,这一段度量随之退休。

★★★ 口径必须在**全分辨率**上量(本脚本最重要的一个决定,有实测依据)
----------------------------------------------------------------
旧脚本(motion-fresh.py / doc-consistency.py)把画面缩到 **320×180** 再取帧差。
删掉漂移后,画面靠的是**逐字落位的单帧事件** —— 一帧里多几个汉字。
在 320×180 下,这几百个像素的变化被缩放平均掉,YAVG 落到 0.35 以下 ⇒ **测不到**。
实测(v17,区间 f1500-1600):

    v16 [full-res] still 1%    median YAVG 1.329
    v17 [full-res] still 100%  max    YAVG 0.330     ← 全都在阈值下
    v17 [320x180 ] still 100%  max    YAVG 0.220

于是 motion-fresh 会把 v17 的 S5 报成**连续静止 23.70s**(全片静止率 77.1%),
而同一段在**全分辨率**上每约 20 帧就有一次 ≥0.37 的事件(逐字落位)。
⇒ 「23.7s 死段」是**缩放造成的假象**,不是画面的性质。
   这正是本项目反复踩的那类错:**拿分辨率不够的度量去支撑一个它支撑不了的结论。**
所以本脚本一律全分辨率度量,并把 320×180 只留给「全片静止率」那个历史统计量
(它在旧口径下有定义,跨版本比较时必须注明口径已不适用 —— 见下方结论区)。

★ 四道检查,每一道都能失败:
  ① **声明的覆盖**:相邻声明事件(含片头片尾)间隔 ≤ maxGapFrames。
  ② **测得的覆盖**:**独立于声明** —— 用 ffmpeg `freezedetect` 找冻结区间,
     任何 > maxGapFrames 的冻结都算死段。这条**无法靠改声明蒙混**。
  ③ **声明的可见**:每个声明事件在 ±W 帧窗口内必须真的测到变化(YAVG ≥ THRESH)。
     失败 ⇒ 声明了但观众看不到(即验收文档里的「哑事件」)。
  ④ **声明的静止**:每个声明的 hold,区间内每一帧都必须 < THRESH。
     失败 ⇒ 声明是静止的,实际在动(hold 是假的)。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("marketing/promo-shotcraft")
EVENTS = ROOT / "src" / "events.json"
TIMELINE = ROOT / "src" / "timeline.ts"
OUT = Path(".tmp/motion-gate.txt")

FPS = 30
# 全分辨率下的「无可见变化」阈值。同值沿用旧口径的标称值,但**标定环境变了**:
# 实测 v17 的逐字落位事件在全分辨率下是 0.37~1.01,而死段 < 0.35 ⇒ 有可分离的间隔。
THRESH = 0.35
# ★ YMAX 口径:YAVG 是**全帧平均**,对**小面积**事件失灵。
#   实测(promo-v17):S5「结论行标注线画完」在 ±4 帧窗口内峰值 YAVG 仅 0.0003,
#   而同一窗口 YMAX=32.0(该线确实画出来了;注意 32.0 出现在 f2576-2577,
#   f2580 本身只有 8.0 —— 判据用的是窗口峰值,不是单帧值)。
#   加入 YMAX 后,「声明了但测不到」从 **30/140 降到 1/140**(独立复核复现了这个数)。
#
# ★★ 但**下面这句原话是错的,已由独立复核证伪,留档以免重蹈**:
#   我原先写「真的什么都没发生的帧 YMAX ≤ 2.0(实测 f3629 = 2.0)⇒ 阈值 10 落在
#   大间隔中间」。复核者在全片逐帧统计后给出真实分布:**只有 337/5249 帧(6.4%)
#   的 YMAX ≤ 2**;有 **215 帧落在 2~21 之间**;而 YAVG 判为「静止」的 2875 帧里
#   **69.7% 的 YMAX ≥ 10**。⇒ 「空帧 ≤2」是从**单帧(n=1)**推出来的,
#   与「真事件 ≥21」之间**并不存在**我说的那个大间隔。
#   这是本项目第五次「拿样本量不够的证据支撑结论」,而且是我自己犯的。
#   阈值 10 因此只是一个**经验取值**,不是标定出来的分界点。
#
# ⇒ **③ 目前是弱检查**:它的判据能通过全部 ±4 窗口的 **92.21%**,失败窗口基本就是
#   ② 检出的冻结区间,所以它与 ② 高度重合、独立价值有限。**下一步应重设计 ③**
#   (例如改用「该帧窗口相对该镜中位帧差的倍数」这类自适应判据),或直接并入 ②。
#   在此之前,③ 的结论只能读作「这个事件落在冻结区间里」,不能读作「这个事件看不见」。
YMAX_THRESH = 10.0
VIS_W = 4          # 声明帧与观感峰值可能差几帧,给 ±4 帧窗口
FREEZE_NOISE = "-60dB"

_DEFAULT = "marketing/promo-shotcraft/out/promo-v17.mp4"
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
if _args:
    MP4 = _args[0]
else:
    for name in ("promo-v17.mp4", "promo-v16.mp4"):
        if (ROOT / "out" / name).exists():
            MP4 = str(ROOT / "out" / name)
            break
    else:
        MP4 = _DEFAULT
if not Path(MP4).exists():
    raise SystemExit(f"film not found: {MP4}\n  usage: uv run python {sys.argv[0]} <film.mp4>")

if not EVENTS.exists():
    raise SystemExit(
        f"missing {EVENTS} -- the declaration side of the semantic-event gate.\n"
        "  Without it checks 1/3/4 cannot run. That is a FAILURE, not a pass."
    )
decl = json.loads(EVENTS.read_text(encoding="utf-8"))
events = sorted(decl["events"], key=lambda e: e["frame"])
holds = sorted(decl["holds"], key=lambda h: h["from"])
max_gap = int(decl.get("maxGapFrames", 60))

tl = TIMELINE.read_text(encoding="utf-8")
shots = {m.group(1): (int(m.group(2)), int(m.group(3)))
         for m in re.finditer(r"\{id: '(S\d)', from: (\d+), duration: (\d+)", tl)}
if not shots:
    raise SystemExit("could not parse SHOTS from timeline.ts -- refusing to guess")
total = max(a + d for a, d in shots.values())


def shot_of(f: int) -> str:
    for s, (a, d) in shots.items():
        if a <= f < a + d:
            return s
    return "?"


# ── ② 独立测得的冻结区间(不依赖声明) ──────────────────────────
r = subprocess.run(
    ["ffmpeg", "-hide_banner", "-i", MP4,
     "-vf", f"freezedetect=n={FREEZE_NOISE}:d={max_gap / FPS:.3f}",
     "-f", "null", "-"],
    capture_output=True, text=True, encoding="utf-8", errors="ignore",
)
log = r.stdout + r.stderr
f_starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
f_ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", log)]
f_durs = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", log)]
freezes = sorted(zip(f_starts, f_ends, f_durs), key=lambda t: -t[2])
if r.returncode != 0:
    # ★★ 这里曾经写成 `if "freezedetect" not in log: 失败` —— 那是**反的**,已实测纠正:
    #   freezedetect 只在**检出冻结时**才把 "freezedetect" 写进日志。
    #   实测(v17):d=2s → 日志 61 行、含该子串、5 次 freeze_duration;
    #             d=999s(无冻结)→ 日志 46 行、**不含**该子串、0 次。
    #   ⇒ 旧守卫在「画面干净、零冻结」时必然触发,于是 ② 永远不可能通过 ——
    #     一个**永远失败**的检查与「永远成功」同样没用(独立复核发现,我复验确认)。
    #   正确判据是 **ffmpeg 的返回码**:过滤器名写错/图无效会非零退出;跑成功且无冻结则返回 0。
    raise SystemExit(
        f"freezedetect failed (ffmpeg exit {r.returncode}) -- cannot verify coverage; "
        "treating as failure rather than assuming 'no freezes'"
    )

# ── ③/④ 全分辨率逐帧 YAVG + YMAX ──────────────────────────────
# ★ 为什么要同时取 YMAX(见上方常量处的标定):只用 YAVG 会把**细线/小字**这类
#   真实但小面积的事件判成「不可见」——实测 30/140 个声明事件被误判,
#   其中 S5 标注线画完那一帧 YAVG=0.0003 而 YMAX=32.0。
r2 = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", MP4,
     "-vf", "tblend=all_mode=difference,signalstats,metadata=print:file=-",
     "-f", "null", "-"],
    capture_output=True, text=True, encoding="utf-8", errors="ignore",
)
log2 = r2.stdout + r2.stderr
vals = [float(x) for x in re.findall(r"signalstats\.YAVG=([\d.eE+-]+)", log2)]
xmax = [float(x) for x in re.findall(r"signalstats\.YMAX=([\d.eE+-]+)", log2)]
if not vals:
    raise SystemExit("no YAVG measured (full-res) -- do NOT read this as 'nothing moved'. "
                     "check that metadata=print carries :file=-")
if len(xmax) != len(vals):
    # 两条序列不等长 ⇒ 索引会错位,产出一个「看起来合理但错误」的结论。宁可报错。
    raise SystemExit(f"YAVG/YMAX length mismatch ({len(vals)} vs {len(xmax)}) -- "
                     "refusing to align them by guess")
nframes = len(vals) + 1

# ① 声明的覆盖
marks = [0] + [e["frame"] for e in events] + [total]
gaps = [(marks[i + 1] - marks[i], marks[i], marks[i + 1]) for i in range(len(marks) - 1)]
worst_gap, gap_a, gap_b = max(gaps)

# ③ 声明的可见
invisible = []
for e in events:
    f = e["frame"]
    lo, hi = max(0, f - VIS_W), min(len(vals), f + VIS_W + 1)
    peak = max(vals[lo:hi]) if lo < hi else 0.0
    peakx = max(xmax[lo:hi]) if lo < hi else 0.0
    if peak < THRESH and peakx < YMAX_THRESH:
        invisible.append((e, peak, peakx))

# ④ 声明的静止
moving_holds = []
for h in holds:
    lo, hi = max(0, h["from"]), min(len(vals), h["to"])
    seg = vals[lo:hi]
    if not seg:
        moving_holds.append((h, None, 0.0))
        continue
    peak = max(seg)
    if peak >= THRESH:
        moving_holds.append((h, seg.index(peak) + lo, peak))

ok = (worst_gap <= max_gap) and (not freezes) and (not invisible) and (not moving_holds)

lines = [
    "=" * 78,
    "语义事件度量(诊断记录;不作验收判据)",
    "=" * 78,
    "",
    f"  成片      : {MP4}",
    f"  帧数      : {nframes} ({nframes / FPS:.2f}s)   时间轴 TOTAL={total}",
    f"  度量口径  : **全分辨率** tblend 帧差;静止判据 YAVG < {THRESH}"
    f" 且 YMAX < {YMAX_THRESH}",
    "              为什么要全分辨率:320x180 会把「逐字落位」的单帧事件平均掉,",
    "              实测会把 v17 的 S5 误报成连续静止 23.70s(全片静止率 77.1%)。",
    f"  声明侧    : {EVENTS}  ({len(events)} 事件 / {len(holds)} hold)",
    "",
    f"  ① 声明的覆盖(相邻事件间隔上限 {max_gap} 帧 = {max_gap / FPS:.1f}s)",
    f"     最大间隔 {worst_gap} 帧  f{gap_a} -> f{gap_b}  ({shot_of(gap_a)})",
]
if worst_gap <= max_gap:
    lines.append("     ✓ 声明本身无死段")
else:
    lines.append(f"     ✗ 超过上限 —— 声明里就有「什么都没发生」的区间")
    for g, a, b in sorted(gaps, reverse=True)[:6]:
        if g > max_gap:
            lines.append(f"       ★ {g:3} 帧  f{a} -> f{b}  ({shot_of(a)})")

lines += ["", f"  ② 测得的冻结(独立于声明;freezedetect n={FREEZE_NOISE}, "
              f"d={max_gap / FPS:.3f}s)"]
if not freezes:
    lines.append(f"     ✓ 无超过 {max_gap / FPS:.1f}s 的冻结区间")
else:
    lines.append(f"     ✗ {len(freezes)} 段冻结超过 {max_gap / FPS:.1f}s —— 这是"
                 f"**实测死段**,改声明不能消除")
    for a, b, d in freezes[:10]:
        lines.append(f"       ★ f{int(a * FPS):5}-{int(b * FPS):5}  {d:6.2f}s  "
                     f"({shot_of(int(a * FPS))})")

lines += ["", f"  ③ 声明的可见性(±{VIS_W} 帧内需 YAVG >= {THRESH} **或** "
              f"YMAX >= {YMAX_THRESH}(细线/小字事件只有后者测得到))"]
if not invisible:
    lines.append(f"     ✓ {len(events)} 个声明事件全部测到画面变化")
else:
    lines.append(f"     ✗ {len(invisible)}/{len(events)} 个事件测不到变化(声明了但看不到)")
    for e, peak, peakx in invisible:
        lines.append(f"       ★ f{e['frame']} [{e['kind']}] {e['label']}"
                     f"  YAVG {peak:.4f} / YMAX {peakx:.1f}   ({e.get('source', '?')})")
lines.append("     ⚠ 弱判据声明:阈值 10 是**经验取值**(见文件头,原「空帧 ≤2」的说法已被")
lines.append("       独立复核证伪)。本检查能通过全部 ±4 窗口的 92.21%,失败窗口基本就是")
lines.append("       ② 检出的冻结区间 ⇒ 与 ② 高度重合。**③ 的结论只能读作「该事件落在冻结")
lines.append("       区间里」,不能读作「该事件看不见」。**下一步应重设计或并入 ②。")

lines += ["", "  ④ 声明的 hold 静止性(声明为静止的区间内每帧都必须 < 阈值)"]
if not moving_holds:
    lines.append(f"     ✓ {len(holds)} 个声明 hold 全部真的静止")
else:
    lines.append(f"     ✗ {len(moving_holds)}/{len(holds)} 个 hold 并不静止")
    for h, at, peak in moving_holds:
        where = f"f{at}" if at is not None else "(空区间)"
        lines.append(f"       ★ [{h['shot']}] f{h['from']}-{h['to']} {h['label']}"
                     f"  峰值 {peak:.3f} @ {where}")

lines += [
    "",
    "  ── 结论 ────────────────────────────────────────────────",
]
if ok:
    lines.append("  ✓ 事件制成立:声明无死段、声明的都可见、声明的静止都真的静止,"
                 "且实测无冻结。")
else:
    if worst_gap > max_gap:
        lines.append(f"  ✗ 声明有死段(最大 {worst_gap} 帧 > {max_gap})")
    if freezes:
        lines.append(f"  ✗ 实测有 {len(freezes)} 段冻结(最长 {freezes[0][2]:.2f}s)"
                     f" —— 与声明无关,是画面的真实性质")
    if invisible:
        lines.append(f"  ✗ 有 {len(invisible)} 个声明事件测不到变化")
    if moving_holds:
        lines.append(f"  ✗ 有 {len(moving_holds)} 个声明的 hold 实际在动")
lines += [
    "",
    "  ⚠ 口径变更提示:本文件度量的是**事件制**。旧文档里的「全片静止率 8.9%」",
    "    是 320x180 口径下的**帧计数**统计量,在事件制下不再可跨版本比较 ——",
    "    v17 在同一口径下是 77.1%,而画面并不更死(见上方「为什么要全分辨率」)。",
    "    引用任何一个静止率数字时,必须同时给出**度量分辨率**与**口径**。",
]

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)

# ★★ 2026-10-07 用户裁决:**不以运动量设门** ⇒ 这里不再 `sys.exit(1)`。
#    本脚本只输出诊断,不阻塞任何流程(上面的 ✗ 是「观察到什么」,不是「不合格」)。
#    若要把它恢复成关卡,取消下面两行注释即可。
# if not ok:
#     sys.exit(1)
