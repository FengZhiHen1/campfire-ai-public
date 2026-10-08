"""盘点所有镜头的**出场淡出**终点值 —— 找出「淡到 0」的那些。

成因(已实测确认,见 verify/collapse-neighbors.py 与 out/dip/strip.jpg):
  出场淡出把 opacity 精确降到 0,于是该段**最后一帧**内容全无;
  而下一段首帧是满的(硬切进),形成「满→空→满」的单帧闪空。
  在 30fps 下 = 33ms,抽帧条上一次可见的白闪。

修法:让淡出**留一个下限**,不要到 0(如 [1, 0.06]),
      这样最后一帧仍有内容,与倒数第二帧连续。
"""
import re
from pathlib import Path

ROOT = Path("marketing/promo-shotcraft/src/shots")
OUT = Path(".tmp/fade-audit.txt")

lines = [
    "=" * 78,
    "出场淡出终点盘点(找「降到 0」的)",
    "=" * 78,
    "",
    "  段            淡出 span         终点   状态",
]
issues = []
for p in sorted(ROOT.glob("S*.tsx")):
    t = p.read_text(encoding="utf-8")
    # 匹配 const fadeOut = interpolate(frame, t.span(a, b), [1, X], ...
    for m in re.finditer(
        r"const\s+(\w*[Ff]ade\w*)\s*=\s*interpolate\(\s*frame,\s*t\.span\(([\d.]+),\s*([\d.]+)\),\s*\[([\d.]+),\s*([\d.]+)\]",
        t,
    ):
        name, a, b, v0, v1 = m.groups()
        to_zero = float(v1) == 0
        status = "★ 降到 0(会产生空帧)" if to_zero else "留有下限 ✓"
        if to_zero:
            issues.append((p.name, name, a, b))
        lines.append(f"  {p.name:14} {name:10} span({a},{b})   {v1:>5}   {status}")

lines += [
    "",
    f"  共 {len(issues)} 处降到 0:",
]
for f, n, a, b in issues:
    lines.append(f"    {f} :: {n}  span({a},{b})")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
