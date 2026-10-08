"""判据校准:三种**性质不同**的对照必须分开,不能并列成同一个「噪声底」。

★★ 为什么重写(独立复核 P5 指出):
  旧版把四个对照并列在同一张「噪声底」表里:
    · 同源双渲 S5            (mean 0.0436)
    · final vs super noBGM   (mean 0.0187)
    · final vs super BGM     (mean 0.2267, 最大 4.30)
  但它们的**性质完全不同** —— BGM 那一对的 S8 = **2.85** 是**真实内容差**
  (superseded BGM 渲于 06:25,早于 fixture 修复 07:53,所以它是旧数据的产物)。
  把那行和「同源双渲」并列,会让人以为 0.09 是统一的噪声门限,
  进而**漏掉真实改动**(S8 那种改动在别的段上平均差只有 0.047,正落在噪声带内)。

  本版按三类分开,并且**用三类之间的互相印证来判定「哪些对其实是同源」**。

三类:
  A. **同源双渲**(同一份源码渲两次)      → 这是**纯噪声底**,判据的唯一来源
  B. **同版本异音轨**(同源码,BGM/无BGM) → 画面必须**完全相同**(差 0);
     若不为 0,说明这一对**并非同源** —— 这本身就是证据
  C. **跨版本**(源码确实改过)            → 差异里混了「真实改动 + 编码噪声」,
     不能用它当噪声底,只能用它找**大改**
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from _timeline import RANGES

ROOT = Path("marketing/promo-shotcraft")
OUT = Path(".tmp/encoder-noise.txt")
W, H = 320, 180
N = W * H
# 镜头区间真源(见 _timeline.py)
SEGS = RANGES
def frames(path: Path):
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vf", f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
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


def compare(a: Path, b: Path) -> tuple[float, float, int, int, dict[str, float]]:
    ds, per_seg = [], {s: [] for s, _, _ in SEGS}
    for i, (x, y) in enumerate(zip(frames(a), frames(b))):
        v = float(np.abs(x - y).mean())
        ds.append(v)
        for s, lo, hi in SEGS:
            if lo <= i < hi:
                per_seg[s].append(v)
                break
    if not ds:
        return (0, 0, 0, 0, {})
    return (float(np.mean(ds)), float(np.max(ds)),
            sum(1 for v in ds if v > 0.05), len(ds),
            {s: float(np.mean(v)) if v else 0.0 for s, v in per_seg.items()})


def get(rel: str) -> Path | None:
    p = ROOT / rel
    return p if p.exists() else None


# ── A. 同源双渲(纯噪声底)──
A = [("同源双渲 S5 run1↔run2", "out/s5det/run1.mp4", "out/s5det/run2.mp4")]
# ── B. 同版本异音轨:画面**必须**相同 ──
B = [("final  BGM↔noBGM", "out/promo-v16.mp4", "out/promo-v16-nobgm.mp4"),
     ("super  BGM↔noBGM", "out/promo-v16-superseded.mp4",
      "out/promo-v16-nobgm-superseded.mp4")]
# ── C. 跨版本(含真实改动)──
C = [("final↔super (BGM)", "out/promo-v16.mp4", "out/promo-v16-superseded.mp4"),
     ("final↔super (noBGM)", "out/promo-v16-nobgm.mp4",
      "out/promo-v16-nobgm-superseded.mp4")]

lines = [
    "=" * 84,
    "判据校准:三类对照必须分开(同源 / 同版本异音轨 / 跨版本)",
    "=" * 84,
    "",
]


def section(title: str, rows, note: str) -> float | None:
    lines.append(f"  ── {title} ──")
    lines.append(f"     {note}")
    lines.append("     对照                        平均差     最大差   差异帧      逐段均值(S4/S5/S8)")
    out = None
    for label, ra, rb in rows:
        a, b = get(ra), get(rb)
        if a is None or b is None:
            lines.append(f"     {label:26} (缺文件)")
            continue
        mean, mx, nz, tot, seg = compare(a, b)
        lines.append(f"     {label:26} {mean:8.5f}  {mx:8.5f}  {nz:5}/{tot:<5}  "
                     f"{seg.get('S4', 0):.4f}/{seg.get('S5', 0):.4f}/{seg.get('S8', 0):.4f}")
        out = mean if out is None else out
    lines.append("")
    return out


noise = section("A. 同源双渲(唯一可作为噪声底的一类)", A,
                "同一份源码渲两次 ⇒ 差异全部来自渲染+编码")
section("B. 同版本异音轨(画面应当**完全相同**)", B,
        "不为 0 ⇒ 这一对其实**并非同源**(重要证据,不是噪声)")
section("C. 跨版本(差异 = 真实改动 + 编码噪声)", C,
        "不能当噪声底,只能用来发现**大改**")

lines += [
    "",
    "  ── 结论 ──────────────────────────────────────────────",
    f"  · 噪声底(仅 A 类可作依据): 平均差 ≈ {noise:.4f} 量级",
    "  · **不能**用一个统一门限同时判 A 与 C: S8 那种「补两段文字」的改动",
    "    在该段平均差达 2.85,而在别的段只有 0.047 —— 落在噪声带内。",
    "    所以「只改了该改的」必须回到**源码层**(verify/source-delta.py),",
    "    而不是任何像素门限。",
    "",
    "  · B 类的用途:若「同版本 BGM↔noBGM」的某段均值显著 >0,",
    "    说明这两个文件**不是同一份源码的产物**。",
    "    实测 super 对的 S8 = 2.85(superseded BGM 渲于 06:25,早于 fixture 修复 07:53),",
    "    而 final 对的 S8 ≈ 0.05 ⇒ **superseded 那一对不是干净对照**,不可用于 A/B。",
]

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
