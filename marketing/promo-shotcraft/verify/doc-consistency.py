"""核对 DELIVERY.md 里的关键数字是否与工作区实际状态一致。

动机:这份文档被反复改过(指纹、运动量、PSNR 计数都更新过多轮),
很容易出现「表格里是旧值、正文里是新值」。文档里的数字如果自相矛盾,
它的举证价值就归零 —— 上一轮已经因为两处**假举证**被审查抓过。
"""
import hashlib
import json
import re
import sys
from pathlib import Path

from _timeline import TOTAL as TL_TOTAL  # 时间轴唯一真源;不再写死 5250

ROOT = Path("marketing/promo-shotcraft")
DOC = ROOT / "DELIVERY.md"
OUT = Path(".tmp/doc-consistency.txt")

doc = DOC.read_text(encoding="utf-8")
lines = ["=" * 74, "DELIVERY.md 数字一致性核对", "=" * 74, ""]

problems = []


def check(name: str, ok: bool, detail: str) -> None:
    lines.append(f"  {'✓' if ok else '✗'} {name}")
    if detail:
        lines.append(f"      {detail}")
    if not ok:
        problems.append(name)


# ── 正片路径 vs 非正片路径 ──────────────────────────────────────
# 判据不能是「src/ 下所有文件都早于成片」—— 那过严:src/probe/ 是开发探针,
# 不在正片路径上(src/Root.tsx 只 import ./Promo 与 ./timeline)。
# 正确判据是「**正片路径上的**文件都早于成片」,且「probe 不在正片路径上」
# 这件事本身要被机械验证,而不是我说了算。
root_src = (ROOT / "src" / "Root.tsx").read_text(encoding="utf-8")
imports_probe = "probe" in root_src
check(
    "正片入口不引用 probe/（故 probe/ 的改动不影响成片）",
    not imports_probe,
    "src/Root.tsx " + (
        "★ 引用了 probe（断言不成立）" if imports_probe
        else "只引用 ./Promo 与 ./timeline"
    ),
)

# ── 指纹 ────────────────────────────────────────────────────────
# ★ 2026-10-07:成片名不再写死,由 render-manifest.json 的 `film` 字段决定 ——
#   那个字段记录「这份源码产生的是哪一版成片」。旧版硬编 promo-v16*,
#   于是重渲出 v17 之后它仍只校验 v16:真正该问的「成片是否对应当前源码」
#   **根本没被检查**(与 P0「清单对样式失明」同型:检查的对象错了)。
_film_rel = None
if (ROOT / "render-manifest.json").exists():
    _film_rel = json.loads(
        (ROOT / "render-manifest.json").read_text(encoding="utf-8")
    ).get("film")
if not _film_rel:
    check("render-manifest.json 指明成片", False, "缺 film 字段;先跑 render-manifest.py")
    _film_names: list[str] = []
else:
    _base = Path(_film_rel).name
    _film_names = [_base, _base.replace(".mp4", "-nobgm.mp4")]
for fname in _film_names:
    p = ROOT / "out" / fname
    if not p.exists():
        check(f"{fname} 存在", False, "文件缺失")
        continue
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    check(f"{fname} 指纹与文档一致", actual.upper() in doc.upper(),
          f"实际 {actual[:24]}…")

# ── 时长 ────────────────────────────────────────────────────────
tl = (ROOT / "src" / "timeline.ts").read_text(encoding="utf-8")
durs = [int(m.group(1)) for m in re.finditer(r"duration: (\d+)", tl)]
total = sum(durs)
check(f"九段合计 = 时间轴 TOTAL({TL_TOTAL} 帧,自洽)", total == TL_TOTAL, f"实际 {total}")

# ── 文档里各段时长是否与 timeline 一致 ──────────────────────────
shots = {m.group(1): int(m.group(3)) // 30
         for m in re.finditer(r"\{id: '(S\d)', from: (\d+), duration: (\d+)", tl)}
mismatch = []
for sid, secs in shots.items():
    # 文档表格里形如 | S1 | 0-119 | 4s |
    m = re.search(rf"\|\s*(?:\*\*)?{sid}(?:\*\*)?\s*\|[^|]*\|\s*(?:\*\*)?(\d+)s", doc)
    if m and int(m.group(1)) != secs:
        mismatch.append(f"{sid}: 文档 {m.group(1)}s vs 实际 {secs}s")
check("文档九段时长与 timeline 一致", not mismatch, "; ".join(mismatch))

# ── 成片是否对应当前源码(内容哈希,不是 mtime) ──────────────────
# ★ 为什么不用 mtime:改一句注释也会让 mtime 变新,于是「源码晚于成片」——
#   但那句注释不影响画面。反过来 mtime 也证明不了「成片是这份源码渲的」。
#   所以比内容哈希(render-manifest.json),并在「免于重渲」时有明确登记。
#
# ★★ 独立复核 P0(已修):清单以前只 glob `src/**`,于是 **apps/web 条目 0 个**,
#   而 src/ 通过 import 依赖 34 个产品文件。复核者的消融证实:
#   改产品 `labels.ts` 的可见文案 → 画面 SHA 变了,而本检查**仍报 0 处不一致**。
#   现在清单由 verify/render-manifest.py 从 import 闭包**推导**(63 个文件,
#   其中 apps/web 34 个),路径是**仓库相对**的(不再是 film-root 相对)。
REPO = ROOT.parents[1]
mf = ROOT / "render-manifest.json"
if mf.exists():
    man = json.loads(mf.read_text(encoding="utf-8"))
    drift, absent = [], []
    for rel, recorded in man["files"].items():
        # 路径是仓库相对的;若指向 ROOT 内则退化为 ROOT 相对(兼容旧清单)
        p = REPO / rel
        if not p.exists():
            p = ROOT / rel
        if not p.exists():
            absent.append(rel)
            continue
        now = hashlib.sha256(p.read_bytes()).hexdigest()
        if now != recorded:
            drift.append(rel)
    n_web = sum(1 for k in man["files"] if k.startswith("apps/web"))
    check(
        "成片对应的源码内容未变（逐文件 sha256 比对，含 apps/web 传递依赖）",
        not drift and not absent,
        (f"★ 有 {len(drift)} 个已改动、{len(absent)} 个缺失" if (drift or absent)
         else f"{len(man['files'])} 个文件一致（其中 apps/web {n_web} 个；非 mtime 判据）"),
    )
    # ★ 自检:清单必须真的覆盖产品代码。否则这个门禁会「静默失明」——
    #   那正是复核者用消融证明过的失败模式。宁可门禁报错,也不要它假通过。
    check(
        "清单覆盖产品代码（apps/web 条目数 > 0）",
        n_web > 0,
        (f"apps/web 条目 {n_web} 个" if n_web > 0
         else "★ apps/web 条目为 0 —— 清单对产品代码失明,跑 verify/render-manifest.py 重建"),
    )
    # ★★ 自检(P0 修复,2026-10-07):与上一条同型,但盯的是**样式层**。
    #   影片经副作用 import 引入 4 个产品 CSS,另纳入视觉契约真源
    #   docs/design/tokens.css ⇒ CSS 条目至少 5 个。此前正则要求 `from`,
    #   4 条副作用 import 一条都进不了清单 —— 消融证实:改 tokens.css
    #   画面变了,而本检查仍报「0 处不一致 / exit 0」。若此处为 0/过少,
    #   说明样式解析又坏了,先跑 verify/render-manifest.py 重建再谈验收。
    n_css = sum(1 for k in man["files"] if k.endswith(".css"))
    check(
        "清单覆盖样式层（css 条目数 ≥ 5，含副作用 import 与 tokens 真源）",
        n_css >= 5,
        (f"css 条目 {n_css} 个" if n_css >= 5
         else "★ css 条目过少 —— 清单对样式层失明（P0 同型失败）,"
              "跑 verify/render-manifest.py 重建"),
    )
    for d in drift[:8]:
        lines.append(f"      ★ 已改动: {d}")
    for a in absent[:8]:
        lines.append(f"      ★ 缺失  : {a}")
else:
    check("render-manifest.json 存在", False, "缺失;跑 verify/render-manifest.py")

# ── 运动量:静止率只作**记录**,判据改用**实测冻结** ──────────────
# ★★ 2026-10-07 口径更正(本轮重要发现,详见 ROUND_STATE.md §2):
#   旧的「全片静止率」是 **320x180 缩放后**的**帧计数**统计量。删掉相机周期漂移后,
#   画面靠的是**逐字落位的单帧事件**;一帧多几个汉字,在 320x180 下被缩放平均掉。
#   实测同一段(f1500-1600):全分辨率下 v17 每 ~20 帧有一次 >=0.37 的事件,
#   而 320x180 口径仍记它「静止」⇒ 整段被报成「连续静止 23.70s」。
#   于是 v16→v17 的 8.9%→77.1% **主要是口径差,不是画面变死**。
#   在度量本身失效的情况下拿它当 pass/fail,会给出错误结论
#   (与 P0「清单对样式失明」同型:检查的对象错了)。
#   ⇒ 静止率继续**测**并写进报告(它是事实),但**不再作为判据**;
#     判据改为 `freezedetect`(用途专用,且实测在两种分辨率下结论一致),
#     它回答真正要问的问题:**有没有「什么都没发生」的死段。**
import subprocess  # noqa: E402

film = (ROOT / "out" / Path(_film_rel).name) if _film_rel else ROOT / "out" / "promo-v16.mp4"
if film.exists():
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(film),
         "-vf", ("scale=320:180,tblend=all_mode=difference,signalstats,"
                 "metadata=print:key=lavfi.signalstats.YAVG:file=-"),
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    yv = [float(x) for x in re.findall(r"YAVG=([\d.eE+-]+)", r.stdout + r.stderr)]
    if not yv:
        # 零结果绝不能当成「静止率 0%」
        check("静止率可测（未采到 YAVG 视为失败）", False,
              "ffmpeg 未输出任何 YAVG —— 检查 metadata=print 是否带 :file=-")
    else:
        pct = sum(1 for v in yv if v < 0.35) / (len(yv) + 1) * 100
        lines.append(f"      · 仅记录(非判据): 320x180 全片静止率 = {pct:.1f}%"
                     f" —— 该口径在事件制下失效,不可跨版本比较")

    # ── 判据:实测冻结段(与 verify/motion-gate.py 的 ② 同一口径)─────
    rf = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(film),
         "-vf", "freezedetect=n=-60dB:d=2.000", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    flog = rf.stdout + rf.stderr
    # ★★ 判据必须是 ffmpeg 的**返回码**,不能是「日志里有没有 'freezedetect' 字样」——
    #   该过滤器只在**检出冻结时**才写这个子串(实测:v17 d=2s 有、d=999s 无),
    #   于是「有没有字样」恰好与「画面干不干净」反相关:零冻结 ⇒ 无字样 ⇒ 误判失败。
    #   这个错我在 motion-gate.py 里也犯过,由独立复核抓出后两处一起改。
    if rf.returncode != 0:
        check("冻结可测（freezedetect 未成功运行视为失败）", False,
              f"ffmpeg exit {rf.returncode} —— 不能当成『无冻结』")
    else:
        durs = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", flog)]
        n_frz, longest = len(durs), (max(durs) if durs else 0.0)
        acc = ROOT / "ACCEPTANCE.md"
        hay = doc + (acc.read_text(encoding="utf-8") if acc.exists() else "")
        # ★ 数字必须**挂在当前成片名下**才作数 —— 否则 v16 与 v17 两个数字会互相冒充,
        #   而「文档里的数对应哪一版成片」正是这份检查最该保证的事。
        m = re.search(
            re.escape(film.name)
            + r"[^\n]{0,60}?实测冻结\s*\*{0,2}(\d+)\*{0,2}\s*段[^0-9]{0,12}([\d.]+)\s*s",
            hay,
        )
        ok_doc = (bool(m) and int(m.group(1)) == n_frz
                  and abs(float(m.group(2)) - longest) < 0.05)
        check(
            "实测冻结段数与文档一致（现测；查**文档准确性**,不是运动判据）",
            ok_doc,
            f"实测 {n_frz} 段 / 最长 {longest:.2f}s vs 文档 "
            + (f"{m.group(1)} 段 / {m.group(2)}s" if m else "未登记"),
        )

lines.append("")
lines.append(f"  共 {len(problems)} 处不一致")
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)

# ★★ 非零退出:独立复核 P1 指出,本脚本此前无论查出多少不一致都 exit 0,
#    于是它可以被当成「永不失败的门禁」—— 而一个不会失败的门禁不是门禁。
#    现在有不一致就以非零退出,使其能真正卡住流程(CI / 手工核查)。
if problems:
    sys.exit(1)
