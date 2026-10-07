import io, re
from pathlib import Path
TXT = Path("marketing/promo-shotcraft/out/qa4/motion-v16.txt")
SHOTS = [("S1",0,120),("S2",120,300),("S3",300,540),("S4",540,1500),("S5",1500,2700),
         ("S6",2700,3780),("S7",3780,4560),("S8",4560,4950),("S9",4950,5250)]
THRESH, MIN_RUN = 0.35, 30
vals = {}
for i, line in enumerate(io.open(TXT, encoding="utf-8", errors="ignore")):
    m = re.search(r"YAVG=([\d.eE+-]+)", line)
    if m: vals[i] = float(m.group(1))
def shot_of(f):
    for n,a,b in SHOTS:
        if a <= f < b: return n
    return "?"
frames = sorted(vals)
runs, start = [], None
for f in frames:
    still = vals[f] < THRESH
    if still and start is None: start = f
    if not still and start is not None:
        if f - start >= MIN_RUN: runs.append((start,f))
        start = None
if start is not None and frames[-1]-start >= MIN_RUN: runs.append((start,frames[-1]))
total_still = sum(1 for f in frames if vals[f] < THRESH)
out = [f"全片 {len(frames)+1} 帧 ({round((len(frames)+1)/30,1)}s)"]
out.append(f"静止帧 {total_still} = {round(total_still/(len(frames)+1)*100,1)}%")
out.append("")
for n,a,b in SHOTS:
    seg = [f for f in frames if a <= f < b]
    s = sum(1 for f in seg if vals[f] < THRESH)
    mx = max((vals[f] for f in seg), default=0)
    out.append(f"  {n}: 静止 {round(s/max(1,len(seg))*100,1):5}% | 峰值YAVG {mx:.2f}")
runs.sort(key=lambda r: r[1]-r[0], reverse=True)
out.append("")
out.append(f"最长静止区间({len(runs)} 个 ≥1s):")
for a,b in runs[:8]:
    out.append(f"  f{a:5}-{b:5}  {(b-a)/30:5.2f}s  {shot_of(a)}")
Path(".tmp/motion-v16.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
