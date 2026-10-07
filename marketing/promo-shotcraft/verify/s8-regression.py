"""检查我自己的修复是否引入回归:S8 的来源行变长(多两段)⇒ 卡片更高 ⇒
滚动范围变了。要确认:
  ① 滚动终点仍落在「虚构样例」那张卡上(不是滚过头或没滚到);
  ② 没有滚出内容底(露白);
  ③ 元素位置实测值(markScrollPx 用的 offsetTop)是否随内容变高而失效。
"""
import asyncio
import json
import subprocess
from pathlib import Path

import asyncpg
import numpy as np
from PIL import Image

OUT = Path(".tmp/s8-regression.txt")
FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
EL = Path("marketing/promo-shotcraft/src/element-metrics.json")

lines = ["=" * 76, "S8 回归检查(来源行变长之后)", "=" * 76, ""]

# ① 元素实测值是否还被使用
el = json.loads(EL.read_text(encoding="utf-8"))
cases = el.get("cases", {})
lines.append("① element-metrics.json 里 cases 的记录:")
marks = cases.get("marks", {})
for k, v in marks.items():
    lines.append(f"     {k}: offsetTop={v.get('offsetTop')} ratio={v.get('ratio')} scrollPx={v.get('scrollPx')}")

# 关键:这些 offsetTop 是在**旧的(来源行短的)**页面上量的吗?
# 若是,则来源行变长后 offsetTop 会下移,滚动终点就偏了。
lines.append("")
lines.append("  ⚠ 关键问题:offsetTop 是在哪个版本的页面上量的?")
lines.append("     element-metrics.json 的 mtime:")
lines.append(f"       {EL.stat().st_mtime}")
import datetime
lines.append(f"       {datetime.datetime.fromtimestamp(EL.stat().st_mtime)}")
DATA = Path("marketing/promo-shotcraft/src/fixtures/data.generated.ts")
lines.append("     data.generated.ts(来源行数据变更)mtime:")
lines.append(f"       {datetime.datetime.fromtimestamp(DATA.stat().st_mtime)}")

el_t = EL.stat().st_mtime
data_t = DATA.stat().st_mtime
lines.append("")
if el_t < data_t:
    lines.append("     ★ element-metrics.json **早于** fixture 变更 ⇒ 量的是旧页面!")
    lines.append("       来源行加长后各卡片下移,offsetTop 偏小,滚动终点会**落在目标之上**。")
    lines.append("       → 需要重新量 element-metrics。")
else:
    lines.append("     ✓ element-metrics 不早于 fixture ⇒ 位置值仍有效")

# ② 从成片看滚动终点:虚构样例的标签是否在画面里
lines.append("")
lines.append("② 成片里滚动终点(绝对 f4930 附近)是否能看到「虚构样例」卡:")
for n in (4900, 4930, 4945):
    p = Path(f"marketing/promo-shotcraft/out/s8reg/f{n}.png")
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", FILM,
                        "-vf", f"select=eq(n\\,{n})", "-vframes", "1",
                        "-pix_fmt", "rgb24", str(p)], check=True)
    im = Image.open(p).convert("L")
    a = np.asarray(im)
    # 设备屏内内容区(约 x430-870, y180-1010)
    crop = a[180:1010, 430:870]
    std = float(crop.std())
    lines.append(f"     f{n}: 屏内标准差 {std:.1f}  非纸色像素 {int((crop < 200).sum())}")
    lines.append(f"            → {p.name}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
