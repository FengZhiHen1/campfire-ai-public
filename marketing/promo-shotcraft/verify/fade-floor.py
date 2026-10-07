"""给所有段末尾的「出场淡出」加一个下限,消除单帧闪空。

★ 实测依据(见 out/dip/strip.jpg):S4→S5 接缝处
    f1495 内容 5339 → f1496 4177 → f1497 1210 → f1498 793 → **f1499 0** → f1500 1885(硬切进)
  即「满 → 渐淡 → 全空一帧 → 满」。那 1 帧(33ms)在抽帧条上是一次可见的白闪。

  量化(verify/invisible-tail.py):每段末尾不可见仅 0.03–0.07s,**低于感知阈值**,
  所以这不是「观众会明显看到黑了半秒」;但它是一个**无谓的接缝瑕疵**,
  且修法零风险(只改淡出终点,不动任何时点与构图)。

修法:把终点 0 改成 0.06 —— 末帧仍留 6% 内容,与倒数第二帧连续,
      视觉上就是正常的「淡出到接近纸面」。
"""
import re
from pathlib import Path

ROOT = Path("marketing/promo-shotcraft/src/shots")
FLOOR = "0.06"

# 只改「出场淡出」(跨度收在段尾、终点为 0),用正则精确匹配,避免误伤别的 interpolate
PATTERN = re.compile(
    r"(const\s+(?:fadeOut|crossFade|sweepFade)\s*=\s*interpolate\(\s*frame,\s*t\.span\([\d.]+,\s*[\d.]+\)\s*,\s*\[1,\s*)0(])"
)

report = []
for p in sorted(ROOT.glob("S*.tsx")):
    src = p.read_text(encoding="utf-8")
    new, n = PATTERN.subn(lambda m: m.group(1) + FLOOR + m.group(2), src)
    if n:
        p.write_text(new, encoding="utf-8")
        report.append((p.name, n))

out = ["=" * 70, "出场淡出加下限", "=" * 70, ""]
for name, n in report:
    out.append(f"  {name}: 改了 {n} 处 → 终点 {FLOOR}")
if not report:
    out.append("  (没有匹配到 —— 检查正则或命名是否变了)")
Path(".tmp/fade-floor.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
