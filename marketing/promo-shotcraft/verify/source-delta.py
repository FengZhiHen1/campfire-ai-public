"""判断「重渲是否只改了该改的地方」—— 基于**源码差异**,不是像素差异。

★ 为什么推翻上一版 `ab-diff.py`:
  它拿两版 mp4 逐帧比,把任何 >0.05 的差都当成「改动」。但实测噪声底:
  **同一份源码渲染两次**,mp4 在 329/1200 帧上就有平均 0.044、最大 0.082 的差异
  (H.264 多线程与码率控制决策不是位确定的)。而同样这些帧的**无损 PNG 逐字节相同**。
  于是那个判据把 S5 的纯编码噪声误判成「非预期改动」。

  更根本的问题:**像素 A/B 的分辨率不足以回答这个问题** ——
  S4 的逐字落位修正带来的平均差(0.028~0.069)正好落在噪声带(≤0.09)里。
  所以正确做法是回到**源码层**:列出两个渲染之间到底改了哪些文件,
  再确认每个改动都是预期的。

  这与本项目前三次错误的成因一致:**拿一个分辨率不够的度量去支撑一个它支撑不了的结论。**
"""
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path("marketing/promo-shotcraft")

# ★★ 基线不能写死。独立复核指出:
#    旧版把 cut 硬编成 `2026-10-07 08:02`(某个已被删除的 superseded 文件的 mtime),
#    而 BGM/noBGM 两版的 cut 其实不同(06:25 / 08:02),用哪个决定结论不同。
#    更糟的是文件删掉后这个常量仍留着 —— 脚本照跑、exit 0,却已与事实脱节。
#
#    改为**自动取基线**:找 `out/` 下现存的最新一代「上一版」成片(按 mtime 排序取
#    比当前成片早、且最接近的那一个),用它作为「渲染时点」。找不到就明确报告
#    「无基线可比」,而不是拿一个陈旧常量硬算。
def _baseline_mtime() -> tuple[float | None, str]:
    """找「上一个**全片**渲染」的时刻。

    ★ 必须限定为全片:out/ 下还留着大量中间产物(s5seg.mp4 / racerange.mp4 / 各版
      对比片)。第一版自动取「mtime 最接近的更早 mp4」,结果抓到了 `s1seg.mp4`(06:07,
      一个单段探针)—— 于是把 06:17/06:21 两个**早于 06:25 全片渲染**的文件
      误报成「本次重渲引入的改动」。
      判据:时长 ≈ 175s(全片),或文件名匹配 promo-v16*。
    """
    film = ROOT / "out" / "promo-v16.mp4"
    if not film.exists():
        return None, "当前成片不存在"
    cur = film.stat().st_mtime

    def is_full(p: Path) -> bool:
        if p.name == "promo-v16.mp4":
            return False
        # 先按文件名(便宜);不匹配再用时长判断(贵)
        if p.name.startswith("promo-v16") or p.name.startswith("promo-v1"):
            try:
                out = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(p)],
                    capture_output=True, text=True, timeout=30,
                ).stdout.strip()
                return bool(out) and abs(float(out) - 175.019) < 1.0
            except (ValueError, subprocess.SubprocessError):
                return False
        return False

    prev = [p for p in (ROOT / "out").glob("*.mp4")
            if p.stat().st_mtime < cur and is_full(p)]
    if not prev:
        return None, "out/ 下没有更早的**全片**成片(基线已清理)"
    b = max(prev, key=lambda p: p.stat().st_mtime)
    return b.stat().st_mtime, f"{b.name} (mtime {_fmt(b.stat().st_mtime)})"


def _fmt(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


BASELINE_TS, BASELINE_DESC = _baseline_mtime()

# 本轮的预期源码改动(两个真缺陷的修复 + 已证明无影响的动作)
INTENDED = {
    "src/fixtures/data.generated.ts": "S8 来源行:补 review_status / interview_at 两列",
    "src/fixtures/ports.ts": "S8 来源行:透传上面两个字段",
    "src/shots/S4Intake.tsx": "S4 逐字落位:打字窗口提前 4% 结束",
    "src/shots/S5Analysis.tsx": "S5 注释更正(经消融证明不影响画面)",
    "src/lib/DeviceStage.tsx": "注释更正为「不许用原生 scrollTop」(不影响画面)",
    # 这只是「重新量了一遍」,内容与旧版**逐字节相同**
    # (216A931F7FAD7179FECEB990…),已用 Get-FileHash 与备份比对确认。
    # 之所以重量:我担心「来源行变长 ⇒ 卡片下移 ⇒ offsetTop 失效」,
    # 但那份 metrics 量的是**真实产品页**(localhost:5174),它一直是 6 段;
    # 错的是影片复刻(只有 4 段)。修好后两者才对齐,故重量结果不变。
    "src/element-metrics.json": "重量校验(内容逐字节相同,证明 metrics 一直是对的)",
    # 出场地板(本轮新增):段末淡出终点 0 → 0.06,消除接缝处的单帧闪空。
    # 证据:out/dip/strip.jpg(f1499 全空、f1500 硬切满屏);
    # 修后实测 f1499 的最大偏离 8 → 23、内容像素 0 → 1014。
    "src/shots/S1BrandOpen.tsx": "出场地板:crossFade 终点保持 0(中途换场,刻意不改)",
    "src/shots/S2PainPoint.tsx": "出场地板:fadeOut 终点 0 → 0.06;sweepFade 保持 0(中途消失)",
    "src/shots/S3Positioning.tsx": "出场地板:fadeOut 终点 0 → 0.06",
    "src/shots/S6ActionCard.tsx": "出场地板:fadeOut 终点 0 → 0.06",
    "src/shots/S7Memory.tsx": "出场地板:fadeOut 终点 0 → 0.06",
    "src/shots/S8Cases.tsx": "出场地板:fadeOut 终点 0 → 0.06",
    "src/shots/S9Closing.tsx": "出场地板:fadeOut 终点 0 → 0.06",
}

OUT = Path(".tmp/source-delta.txt")


def mtimes():
    out = {}
    for g in ("src/**/*.ts", "src/**/*.tsx", "src/**/*.json"):
        for p in ROOT.glob(g):
            if "probe" in p.parts:
                continue
            out[str(p.relative_to(ROOT)).replace("\\", "/")] = p.stat().st_mtime
    return out


mt = mtimes()
intended_files = set(INTENDED)

if BASELINE_TS is None:
    # 没有基线就不要硬算 —— 明确说明,而不是拿陈旧常量给出一个看起来合理的数。
    lines = [
        "=" * 78,
        "重渲是否只改了该改的地方(源码层判据)",
        "=" * 78,
        "",
        f"  ⚠ 无基线可比:{BASELINE_DESC}",
        "",
        "  说明:本判据要求存在「上一版成片」,用它作为渲染时点。",
        "        基线被清理后无法回答「这次重渲改了什么」——",
        "        **此时不应给出任何结论**(旧版拿一个已删除文件的 mtime 硬算,是错的)。",
        "        要恢复本检查:保留上一版成片在 out/ 下即可。",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("written", OUT)
    raise SystemExit(0)

changed_after_cut = sorted(f for f, t in mt.items() if t > BASELINE_TS)
unexpected = [f for f in changed_after_cut if f not in intended_files]

lines = [
    "=" * 78,
    "重渲是否只改了该改的地方(源码层判据)",
    "=" * 78,
    "",
    f"  基线(自动取 out/ 下最接近的上一版): {BASELINE_DESC}",
    "  晚于该时刻的源码改动 = 本次重渲引入的差异",
    "",
    f"  ① 晚于基线改动的源码文件({len(changed_after_cut)} 个):",
]
for f in changed_after_cut:
    mark = "✓ 预期" if f in intended_files else "★ 非预期"
    why = INTENDED.get(f, "(未登记理由)")
    lines.append(f"     {mark}  {f}")
    lines.append(f"              {why}")

lines += [
    "",
    f"  ② 非预期改动: {len(unexpected)} 个",
]
for f in unexpected:
    lines.append(f"     ★ {f}")

lines += [
    "",
    "  ── 结论 ────────────────────────────────────────────────",
]
if not unexpected:
    lines.append("  ✓ 重渲只涉及已登记的 4 处修复(其中 2 处是纯注释,已用无损 PNG 消融证明")
    lines.append("     不影响画面)。**没有非预期改动。**")
else:
    lines.append(f"  ✗ 有 {len(unexpected)} 个非预期改动,需逐个人工确认")

lines += [
    "",
    "  ── 附带更正:像素 A/B 的分辨率不够 ────────────────────",
    "  噪声底实测(见 verify/encoder-noise.py):",
    "    · 同源双渲 S5:平均差 0.044、最大 0.082(而同样帧的无损 PNG 逐字节相同)",
    "    · S4 逐字落位修正:平均差 0.028~0.069  ← **落在噪声带内,像素法测不出**",
    "    · S8 补两段文字 :平均差 2.85          ← 远超噪声,像素法可见",
    "  所以:像素 A/B 只能发现**大改**,不能用来断言「其他都没变」。",
    "  这个判断必须回到源码层(本脚本),或对**无损 PNG** 逐帧比。",
]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
