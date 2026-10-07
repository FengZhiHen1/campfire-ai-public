"""查清 S5 为什么也变了 —— 这是我没预期的差异。

先量化差异幅度:若 S5 的差异远小于 S4/S8,可能是编码噪声;若同量级,是真实内容变化。
再定位差异出现在画面的哪个位置 —— 那能直接指出改的是什么。
"""
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

A = "marketing/promo-shotcraft/out/promo-v16.mp4"
B = "marketing/promo-shotcraft/out/promo-v16-superseded.mp4"
OUT = Path(".tmp/s5-why.txt")
W, H = 320, 180
N = W * H

# ★ 对照文件必须存在,否则报错 —— 不要把「读不到」当成 0/空(同 seam-before-after.py)。
_miss = [p for p in (A, B) if not Path(p).exists()]
if _miss:
    raise SystemExit("★ 缺少对照文件,无法比较:\n" + "\n".join(f"   {p}" for p in _miss))


def stream(path):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path,
                          "-vf", f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE)
    assert p.stdout is not None
    while True:
        buf = p.stdout.read(N)
        if len(buf) < N:
            break
        yield np.frombuffer(buf, dtype=np.uint8).astype(np.int16)
    p.stdout.close()
    p.wait()


diffs = [float(np.abs(a - b).mean()) for a, b in zip(stream(A), stream(B))]


def stats(lo, hi, name):
    seg = diffs[lo:hi]
    nz = [d for d in seg if d > 0.05]
    return (f"  {name}: 平均 {np.mean(seg):.3f}  最大 {max(seg):.3f}  "
            f"有差异帧 {len(nz)}/{len(seg)}  非零均值 {np.mean(nz) if nz else 0:.3f}")


lines = [
    "=" * 74,
    "S5 差异的量级与位置",
    "=" * 74,
    "",
    "① 各段差异量级对比(判断是内容变化还是编码噪声):",
    stats(540, 1500, "S4(已知改了逐字落位)"),
    stats(4560, 4950, "S8(已知改了来源行)  "),
    stats(1500, 2700, "S5(非预期!)        "),
    stats(0, 120, "S1(应无差异)        "),
    stats(2700, 3780, "S6(应无差异)        "),
]

# ② 差异出现在画面的哪个位置(取 S5 差异最大的一帧)
worst = max(range(1500, 2700), key=lambda f: diffs[f])
lines.append("")
lines.append(f"② S5 差异最大的帧 = f{worst} (平均差 {diffs[worst]:.3f})")
lines.append("   把它两版裁出来对比:")
for tag, path in (("final", A), ("super", B)):
    p = Path(f"marketing/promo-shotcraft/out/s5why/{tag}_{worst}.png")
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                        "-vf", f"select=eq(n\\,{worst})", "-vframes", "1",
                        "-pix_fmt", "rgb24", str(p)], check=True)
    lines.append(f"     {tag}: {p.name}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
