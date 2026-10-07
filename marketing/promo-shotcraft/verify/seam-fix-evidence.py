"""对**修后**的成片,把 8 处段边界的末帧抽出来拼图,作为修复的视觉证据。

对照:每个边界取「前一段末帧」与「后一段首帧」,看末帧是否还有内容。
修复前末帧是纯纸面(92% --bg),修复后应仍保留 6% 内容。
"""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OLD = "marketing/promo-shotcraft/out/promo-v16-superseded2.mp4"
W = Path("marketing/promo-shotcraft/out/seamfix")
W.mkdir(parents=True, exist_ok=True)

# ★ 对照文件必须存在,否则报错 —— 不要把「读不到」画成「留白」。
#   (同 seam-before-after.py:清理后曾静默给出比真实更好的结论。)
_miss = [p for p in (OLD, FILM) if not Path(p).exists()]
if _miss:
    raise SystemExit(
        "★ 缺少对照文件,无法并排比较(不要把它当成『修前是空白』):\n"
        + "\n".join(f"   {p}" for p in _miss)
    )

BOUNDS = [("S1→S2", 119), ("S2→S3", 299), ("S3→S4", 539), ("S4→S5", 1499),
          ("S5→S6", 2699), ("S6→S7", 3779), ("S7→S8", 4559), ("S8→S9", 4949)]

TW, TH = 200, 113
rows = []
for tag, f in BOUNDS:
    row = []
    for src, label in ((OLD, "修前"), (FILM, "修后")):
        p = W / f"{label}_{f}.png"
        if not p.exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                            "-vf", f"select=eq(n\\,{f}),scale={TW}:{TH}",
                            "-vframes", "1", str(p)], check=True)
        row.append(p)
    rows.append((tag, f, row))

sheet = Image.new("RGB", (TW * 2 + 130, (TH + 20) * len(rows)), (255, 255, 255))
d = ImageDraw.Draw(sheet)
for i, (tag, f, row) in enumerate(rows):
    y = i * (TH + 20)
    d.text((4, y + TH // 2), f"{tag}\nf{f}", fill=(0, 0, 0))
    for j, p in enumerate(row):
        with Image.open(p) as im:
            sheet.paste(im.convert("RGB"), (120 + j * TW, y))
        d.text((120 + j * TW + 4, y + TH + 2), ["修前(末帧全空)", "修后(末帧留 6%)"][j],
               fill=(120, 0, 0) if j == 0 else (0, 100, 0))

out = W / "seams-compare.jpg"
sheet.save(out, quality=90)
print("written", out, sheet.size)
