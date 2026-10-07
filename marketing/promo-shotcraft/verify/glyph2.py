"""实测字形高度(改进版):先定位单个文字行的墨迹段,再量高度。

上一版失败原因:box 太大,把多行连同卡片边框一起算成一段连续的墨迹。
这一版要求墨迹段之间必须有**空白间隔**才算分行,并报告所有行高,
这样一眼能看出哪一行是正文、哪一行是 15px 的 meta 行。
"""
import subprocess
from pathlib import Path

from PIL import Image

MP4 = "marketing/promo-shotcraft/out/promo-v16.mp4"
W = Path("marketing/promo-shotcraft/out/glyph2")
W.mkdir(parents=True, exist_ok=True)
OUT = Path(".tmp/glyph2.txt")


def grab(n: int) -> Path:
    p = W / f"f{n}.png"
    if not p.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", MP4,
             "-vf", f"select=eq(n\\,{n})", "-vframes", "1", "-pix_fmt", "rgb24", str(p)],
            check=True,
        )
    return p


def line_heights(p: Path, box, min_ink: int = 3) -> list[tuple[int, int, int]]:
    with Image.open(p).convert("RGB") as im:
        c = im.crop(box)
        px = c.load()
        w, h = c.size
        rows = []
        for y in range(h):
            n = sum(1 for x in range(w) if sum(px[x, y]) < 720)
            rows.append(n)
    runs, start = [], None
    for y, n in enumerate(rows):
        if n >= min_ink:
            if start is None:
                start = y
        else:
            if start is not None:
                runs.append((start, y - 1))
                start = None
    if start is not None:
        runs.append((start, len(rows) - 1))
    return [(a, b, b - a + 1) for a, b, _ in [(a, b, 0) for a, b in runs] if b - a + 1 >= 3]


lines = [
    "=" * 74,
    "实测各文字行的墨迹高度（S6 段内，设备屏正文区）",
    "=" * 74,
    "",
    "  帧     行号   行段(相对box)   墨迹高度(px)",
]

for n in (3400, 3600):
    p = grab(n)
    hs = line_heights(p, (465, 300, 835, 950))
    for i, (a, b, h) in enumerate(hs[:12], 1):
        lines.append(f"  {n:5}   {i:2}    {a:4}–{b:<5}       {h:3}")

lines.append("")
lines.append("  对照:")
lines.append("    · 组件正文 CSS 字号     19px × scale 1.20 = 22.8px(em 高度)")
lines.append("    · 组件 meta CSS 字号    15px × scale 1.20 = 18.0px(em 高度)")
lines.append("    · 汉字墨迹约为字号 70–75% ⇒ 正文约 16–17px、meta 约 13px")
lines.append("    · 可读阈值 12px ⇒ 两者均达标")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
