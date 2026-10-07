"""生成全片接触印相表(contact sheet)——用来「通看一遍」成片。

★ 为什么要做:
  我反复声明「所有指标达标,但我没有真的从头到尾看过」。指标是分段的、
  逐项的,而**连续观看**能暴露指标看不见的问题:节奏断裂、段落间风格漂移、
  某个镜头的构图在全片语境里显得突兀、swoosh 式转场过多等。
  我没有播放器,能做的最接近的事是:按固定间隔抽帧拼成大图,一次看完。

做法:每 2 秒抽一帧(共 88 帧),拼成 11×8 的网格。
"""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
W = Path("marketing/promo-shotcraft/out/contact")
W.mkdir(parents=True, exist_ok=True)
OUT = Path(".tmp/contact-sheet.txt")

STEP = 60          # 每 2 秒一帧
TOTAL = 5250
COLS, ROWS = 8, 11  # 88 帧
TW, TH = 240, 135   # 每格缩略图尺寸

frames = list(range(0, TOTAL, STEP))[:COLS * ROWS]

tiles = []
for f in frames:
    p = W / f"f{f:05}.png"
    if not p.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", FILM,
             "-vf", f"select=eq(n\\,{f}),scale={TW}:{TH}", "-vframes", "1", str(p)],
            check=True,
        )
    tiles.append((f, p))

LABEL = 16
sheet = Image.new("RGB", (COLS * TW, ROWS * (TH + LABEL)), (250, 246, 240))
d = ImageDraw.Draw(sheet)
SHOTS = [("S1", 0), ("S2", 120), ("S3", 300), ("S4", 540), ("S5", 1500),
         ("S6", 2700), ("S7", 3780), ("S8", 4560), ("S9", 4950)]


def shot_of(f: int) -> str:
    cur = "?"
    for n, a in SHOTS:
        if f >= a:
            cur = n
    return cur


for i, (f, p) in enumerate(tiles):
    c, r = i % COLS, i // COLS
    with Image.open(p) as im:
        sheet.paste(im, (c * TW, r * (TH + LABEL)))
    d.text((c * TW + 3, r * (TH + LABEL) + TH + 1),
           f"{shot_of(f)} f{f} ({f / 30:.0f}s)", fill=(90, 80, 70))

out = W / "sheet.jpg"
sheet.save(out, quality=88)
lines = [
    "全片接触印相表",
    f"  每 {STEP / 30:.0f}s 一帧,共 {len(tiles)} 帧,{COLS}×{ROWS} 网格",
    f"  输出: {out}",
    f"  尺寸: {sheet.size}",
]
OUT.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
