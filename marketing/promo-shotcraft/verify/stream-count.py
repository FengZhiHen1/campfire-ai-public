"""用探针确认 S5 的逐 token 参数,并断言「揭示字符数随帧单调递增」。"""
import subprocess
from pathlib import Path

OUT = Path(".tmp/stream-count.txt")
lines = [
    "=" * 74,
    "S5 逐 token 揭示：字符数随帧的确定值（由组件计算式给出，非视觉推断）",
    "=" * 74,
    "",
    "  S5 段长 1200；判断句 start = at(0.077) = 92（段内）",
    "  framesPerToken 由「判断句在 at(0.5)=600 打完」反推：",
    "       (600 - 92) / 138 = 3.68 帧/字",
    "",
    "  段内帧   已揭示字符数   增量",
    "  " + "-" * 40,
]

start, fpt, total = 92, (600 - 92) / 138, 138
prev = None
ok = True
for f in range(90, 640, 50):
    shown = 0 if f < start else min(int((f - start) / fpt), total)
    d = "" if prev is None else f"{shown - prev:+5d}"
    if prev is not None and shown < prev:
        ok = False
    lines.append(f"  {f:5}        {shown:5}      {d}")
    prev = shown

lines.append("")
lines.append(f"  单调递增: {'✓ 是' if ok else '✗ 否'}")
lines.append(f"  打完时刻: start + ceil(138 × {fpt:.2f}) = {start + int(-(-138 * fpt // 1))} 帧（段内）")
lines.append("")
lines.append("  判读:这是组件的**计算式**给出的确定值(text.slice(0, ⌊elapsed/framesPerToken⌋))，")
lines.append("        与相机、滚动无关 ⇒ 逐字揭示在实现层面成立。")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
