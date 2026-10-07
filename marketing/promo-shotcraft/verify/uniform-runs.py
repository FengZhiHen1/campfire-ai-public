from pathlib import Path
from PIL import Image, ImageStat

WORK = Path("marketing/promo-shotcraft/out/uniform")
files = sorted(WORK.glob("f*.png"))
uni = []
for p in files:
    n = int(p.stem[1:]) - 1
    sd = ImageStat.Stat(Image.open(p).convert("L")).stddev[0]
    if sd < 0.5:
        uni.append(n)

# 归并成连续区间
runs = []
if uni:
    s = prev = uni[0]
    for f in uni[1:]:
        if f != prev + 1:
            runs.append((s, prev)); s = f
        prev = f
    runs.append((s, prev))

def shot(f):
    return ("S1" if f < 120 else "S2" if f < 300 else "S3" if f < 540
            else "S4" if f < 1500 else "S5" if f < 2700 else "S6" if f < 3780
            else "S7" if f < 4560 else "S8" if f < 4950 else "S9")

out = [f"完全均匀帧共 {len(uni)} 帧,归并为 {len(runs)} 个连续区间:", ""]
for a, b in runs:
    out.append(f"  f{a}-{b}  ({b-a+1} 帧 = {(b-a+1)/30:.2f}s)  {shot(a)}")
    # 标出该区间在镜头内的相对位置
    starts = {"S1":0,"S2":120,"S3":300,"S4":540,"S5":1500,"S6":2700,"S7":3780,"S8":4560,"S9":4950}
    lens   = {"S1":120,"S2":180,"S3":240,"S4":960,"S5":1200,"S6":1080,"S7":780,"S8":390,"S9":300}
    sid = shot(a)
    rel_a = (a - starts[sid]) / lens[sid]
    rel_b = (b - starts[sid]) / lens[sid]
    where = "镜头开头" if rel_a < 0.05 else "镜头结尾" if rel_b > 0.95 else "镜头中间"
    out.append(f"        段内 {rel_a:.3f}-{rel_b:.3f} → {where}")
Path(".tmp/uniform-runs.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
