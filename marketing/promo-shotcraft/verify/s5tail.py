import io, re
vals = {}
for i, line in enumerate(io.open("marketing/promo-shotcraft/out/qa4/motion-v16.txt", encoding="utf-8", errors="ignore")):
    m = re.search(r"YAVG=([\d.eE+-]+)", line)
    if m: vals[i] = float(m.group(1))
# S5 = 1500-2699;尾部 0.78→1.0 = 段内 936..1199 → 绝对 2436..2699
seg = [f for f in sorted(vals) if 2436 <= f < 2700]
print(f"S5 尾部(f2436-2699, 段内 0.78-1.0, 约 8.8s):")
print(f"  帧数 {len(seg)}; 静止帧 {sum(1 for f in seg if vals[f] < 0.35)}")
print(f"  最低 YAVG {min(vals[f] for f in seg):.3f}; 最高 {max(vals[f] for f in seg):.3f}")
# 列表化每 0.5s
for a in range(2436, 2700, 15):
    block = [f for f in seg if a <= f < a+15]
    if not block: continue
    mx = max(vals[f] for f in block)
    print(f"    f{a}-{a+14}: 峰值 {mx:.2f}  {'静止' if mx < 0.35 else ''}")
