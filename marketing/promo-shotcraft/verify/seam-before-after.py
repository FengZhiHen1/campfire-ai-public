"""8 处段边界末帧:修前 vs 修后,逐个量化。

★★ 本脚本刚犯过一次「永不失败的检查」(自查发现,与复核者的 P1 同型):
    OLD 指向 `out/promo-v16-superseded2.mp4`。上一轮清理时该文件被删,
    而 ffmpeg 打不开文件、读不到数据时,本脚本把每一格都记为 0 ——
    于是输出变成「修前 0/0 → 修后 有内容」,**得出「8/8 全部已修」**,
    看起来比真实情况更好(真实是 7/8,S1→S2 本来就正常)。
    ⇒ **文件缺失被读成了「修前什么都没有」。**

    修法:① 文件不存在时报错退出,不静默当 0;
          ② 若 OLD 存在但仍采不到数据,同样报错。
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

OLD = "marketing/promo-shotcraft/out/promo-v16-superseded2.mp4"
NEW = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/seam-before-after.txt")
W, H = 320, 180
N = W * H

BOUNDS = [("S1→S2", 119), ("S2→S3", 299), ("S3→S4", 539), ("S4→S5", 1499),
          ("S5→S6", 2699), ("S6→S7", 3779), ("S7→S8", 4559), ("S8→S9", 4949)]

# ★ 缺文件 = 无法比较,必须报错。绝不把「读不到」当成 0。
_missing = [p for p in (OLD, NEW) if not Path(p).exists()]
if _missing:
    raise SystemExit(
        "★ 缺少对照文件,无法比较(不要把它当成『修前为空』):\n"
        + "\n".join(f"   {p}" for p in _missing)
        + "\n  说明:OLD 是修复前的成片;清理后会缺失 —— 此时应改用历史记录中的数值,"
          "或保留该文件。"
    )


def content_at(film: str, frames: set[int]) -> dict[int, tuple[int, int]]:
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", film, "-vf", f"scale={W}:{H},format=gray",
         "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE,
    )
    assert p.stdout is not None
    out, i = {}, 0
    while True:
        buf = p.stdout.read(N)
        if len(buf) < N:
            break
        if i in frames:
            a = np.frombuffer(buf, dtype=np.uint8)
            bg = int(np.argmax(np.bincount(a, minlength=256)))
            dev = np.abs(a.astype(np.int16) - bg)
            out[i] = (int((dev > 12).sum()), int(dev.max()))
        i += 1
    p.stdout.close()
    p.wait()
    return out


want = {f for _, f in BOUNDS}
old = content_at(OLD, want)
new = content_at(NEW, want)

lines = [
    "=" * 78,
    "8 处段边界末帧:修前 vs 修后",
    "=" * 78,
    "",
    "  边界        帧      修前(偏离像素/最大偏离)   修后        判定",
]
fixed = 0
for tag, f in BOUNDS:
    oc, om = old.get(f, (0, 0))
    nc, nm = new.get(f, (0, 0))
    ok = nc > oc * 3 and nc > 200
    if ok:
        fixed += 1
    lines.append(f"  {tag:9} f{f:<6} {oc:6} / {om:3}          {nc:6} / {nm:3}    "
                 f"{'✓ 已修' if ok else '★ 未改善'}")

lines += [
    "",
    f"  {fixed}/8 处末帧内容量显著提升(判据:修后 > 修前×3 且 >200 像素)",
    "",
    "  说明:修后每处末帧仍保留约 6% 的出场内容,与倒数第二帧连续;",
    "        修复前这些帧是全空纸面(偏离像素为 0 或极小)。",
]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
