"""量各镜头在**最大推近**帧的设备框边距,验证目标①的「永不超过 1.3 倍」且不贴边。

做法:对每个设备镜头取推近最大的那一帧,用 PIL 扫深色 bezel 行的上下界。
"""
import subprocess
from pathlib import Path

from PIL import Image

MP4 = "marketing/promo-shotcraft/out/promo-v16.mp4"
WORK = Path("marketing/promo-shotcraft/out/margin")
WORK.mkdir(parents=True, exist_ok=True)
OUT = Path(".tmp/margins.txt")

# 各镜头「推近接近最大」的绝对帧(取段内约 0.9 处)
SAMPLES = [
    ("S3", 300, 240, 0.9),
    ("S4", 540, 960, 0.9),
    ("S5", 1500, 1200, 0.9),
    ("S6", 2700, 1080, 0.9),
    ("S7", 3780, 780, 0.9),
    ("S8", 4560, 390, 0.9),
]

lines = [
    "=" * 74,
    "各镜头最大推近处的设备框边距(画布 1920×1080)",
    "=" * 74,
    "",
    "  段   绝对帧  上间隙  下间隙   判定",
]


def bezel_rows(p: Path):
    im = Image.open(p).convert("RGB")
    w, h = im.size
    px = im.load()
    rows = []
    for y in range(h):
        dark = 0
        for x in range(300, 1000, 5):
            r, g, b = px[x, y]
            if max(r, g, b) < 150:
                dark += 1
        if dark > 5:
            rows.append(y)
    return (rows[0], rows[-1], h) if rows else (None, None, h)


for sid, start, dur, ratio in SAMPLES:
    n = start + int(dur * ratio)
    p = WORK / f"{sid}_{n}.png"
    if not p.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", MP4,
             "-vf", f"select=eq(n\\,{n})", "-vframes", "1", str(p)],
            check=True,
        )
    top, bottom, h = bezel_rows(p)
    if top is None:
        lines.append(f"  {sid}  {n:6}  未检出设备框(可能该帧无设备)")
        continue
    gap_t, gap_b = top, h - 1 - bottom
    verdict = "正常" if min(gap_t, gap_b) >= 12 else ("★ 贴边" if min(gap_t, gap_b) >= 2 else "★ 越界")
    lines.append(f"  {sid}  {n:6}  {gap_t:6}  {gap_b:6}   {verdict}")

lines.append("")
lines.append("  判据:下/上间隙 ≥12px 视为不贴边;≥2px 为贴边;≤0 为越界。")
lines.append("  注:设备框本身由产品 CSS 的 --device-screen-width/height 决定,影片只做 scale。")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
