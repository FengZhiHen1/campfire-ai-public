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
for fname in ("promo-v16.mp4", "promo-v16-nobgm.mp4"):
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
check("九段合计 = 5250 帧", total == 5250, f"实际 {total}")

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
    for d in drift[:8]:
        lines.append(f"      ★ 已改动: {d}")
    for a in absent[:8]:
        lines.append(f"      ★ 缺失  : {a}")
else:
    check("render-manifest.json 存在", False, "缺失;跑 verify/render-manifest.py")

# ── 全片静止率(现测,不读中间文件) ──────────────────────────────
# ★ 原先读 out/qa4/motion-v16.txt —— 那是**上一次渲染**留下的中间产物,
#   重渲后它就过期了,而文档仍引用其中的数字。改成直接从成片量。
import subprocess  # noqa: E402

film = ROOT / "out" / "promo-v16.mp4"
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
        # 全片静止率写在 ACCEPTANCE.md(不是 DELIVERY.md),两处都找
        acc = ROOT / "ACCEPTANCE.md"
        hay = doc + (acc.read_text(encoding="utf-8") if acc.exists() else "")
        m = (re.search(r"全片静止率 \*\*([\d.]+)%\*\*", hay)
             or re.search(r"全片静止率 ([\d.]+)%", hay))
        doc_pct = float(m.group(1)) if m else None
        check(
            "全片静止率与文档一致（现测）",
            doc_pct is not None and abs(doc_pct - pct) < 0.15,
            f"实测 {pct:.1f}% vs 文档 {doc_pct}%",
        )

lines.append("")
lines.append(f"  共 {len(problems)} 处不一致")
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)

# ★★ 非零退出:独立复核 P1 指出,本脚本此前无论查出多少不一致都 exit 0,
#    于是它可以被当成「永不失败的门禁」—— 而一个不会失败的门禁不是门禁。
#    现在有不一致就以非零退出,使其能真正卡住流程(CI / 手工核查)。
if problems:
    sys.exit(1)
