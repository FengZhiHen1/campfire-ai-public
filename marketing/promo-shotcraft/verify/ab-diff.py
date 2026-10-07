"""两版像素差 —— ⚠ 只能发现**大改**,不能证明「其他都没变」。

★★ 本脚本的第一版判据是错的,保留更正记录:
   它把任何「平均差 > 0.05」的帧都当成「改动了」。但实测噪声底是:
   **同一份源码渲染两次**,mp4 在 329/1200 帧上就有平均 0.044、最大 0.082 的差异
   (H.264 多线程与码率控制决策不是位确定的),而**同样那些帧的无损 PNG 逐字节相同**。
   于是它把 S5 的纯编码噪声误报成「非预期改动」,我一度以为重渲跑偏了。

   更根本的问题:**这个度量的分辨率不够**。
     · S4 逐字落位修正 → 平均差 0.028~0.069  ← **落在噪声带内,像素法测不出**
     · S8 补两段文字   → 平均差 2.85         ← 远超噪声,像素法可见
   所以它只能回答「有没有大改」,不能回答「是不是只改了该改的」。

要回答后者,请用 `verify/source-delta.py`(源码层)或对**无损 PNG** 逐帧比。
"""
import subprocess
from pathlib import Path

import numpy as np
from _timeline import RANGES

A = "marketing/promo-shotcraft/out/promo-v16.mp4"
B = "marketing/promo-shotcraft/out/promo-v16-superseded.mp4"
OUT = Path(".tmp/ab-diff.txt")

# ★ 对照文件必须存在,否则报错退出 —— 不要把「读不到」当成 0/空。
#   同型缺陷见 seam-before-after.py:清理 superseded 后,那个脚本曾静默输出
#   「修前全为 0」并得出比真实更好的结论(8/8 而非 7/8)。
_miss = [p for p in (A, B) if not Path(p).exists()]
if _miss:
    raise SystemExit("★ 缺少对照文件,无法比较:\n" + "\n".join(f"   {p}" for p in _miss))

W, H = 320, 180
N = W * H

# ★ 噪声底实测 0.082(最大差),取 0.15 作为「不可能是噪声」的门槛。
#   0.05 那个旧门槛比噪声底还低,必然大量误报。
THRESH = 0.15

# 镜头区间真源(见 _timeline.py)
SEGS = RANGES
EXPECT = {"S4": "预期(逐字落位)", "S8": "预期(来源行补字段)"}


def stream(path: str):
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={W}:{H},format=gray",
         "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE,
    )
    assert p.stdout is not None
    while True:
        buf = p.stdout.read(N)
        if len(buf) < N:
            break
        yield np.frombuffer(buf, dtype=np.uint8).astype(np.int16)
    p.stdout.close()
    p.wait()


diffs = [float(np.abs(a - b).mean()) for a, b in zip(stream(A), stream(B))]


def seg_of(f: int) -> str:
    for n, a, b in SEGS:
        if a <= f < b:
            return n
    return "?"


big = [f for f, d in enumerate(diffs) if d > THRESH]
by_seg: dict[str, list[int]] = {}
for f in big:
    by_seg.setdefault(seg_of(f), []).append(f)

lines = [
    "=" * 76,
    "两版像素差(⚠ 分辨率有限:只能发现大改)",
    "=" * 76,
    f"  最终: {A}",
    f"  旧版: {B}",
    f"  帧数: {len(diffs)}   门槛: 平均差 > {THRESH}(噪声底实测 0.082)",
    "",
    f"  超过门槛的帧: {len(big)}",
    "",
    "  按段:",
]
for n, _, _ in SEGS:
    fs = by_seg.get(n, [])
    if not fs:
        lines.append(f"    {n}: 无大改")
        continue
    lines.append(f"    {n}: {len(fs):4} 帧   f{fs[0]}–{fs[-1]}   {EXPECT.get(n, '★ 非预期')}")

unexpected = sum(len(v) for k, v in by_seg.items() if k not in EXPECT)
lines += [
    "",
    f"  非预期的大改帧: {unexpected}",
    "",
]
if unexpected == 0:
    lines.append("  ✓ 没有非预期的大改(注意:这只说明**没有大改**,不等于「其他都没变」)")
else:
    lines.append("  ✗ 有非预期大改 ⇒ 需查明")

lines += [
    "",
    "  ── 这个脚本**不能**回答的问题 ────────────────────────────",
    "  「是不是只改了该改的」请用 verify/source-delta.py。",
    "  本轮实测:S4 的逐字落位修正(平均差 0.028~0.069)就落在噪声带里,",
    "  本脚本看不见它 —— 也就是说**用像素 A/B 既会误报、又会漏报**。",
]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
