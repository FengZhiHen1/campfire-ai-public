"""验证 S1 打字期(f26-51)是否**真的**在动 —— 指标说它静止,眼睛是否同意?

背景:S1 的 2s 窗口 f26-105 被帧差判为「无可见变化」。但其中 f26-51 是副标打字期,
每个字应当逐字出现。帧差测不出是因为**细笔画小字在大片空白上的整帧平均太小**。

判据不能再用帧差(那正是被测的口径)。改用两种独立口径:
  ① 无损抽帧后比较**文字区域**的像素差(裁到副标所在带)
  ② 直接数该区域「有墨迹的像素数」是否随时间单调增长
若两者都显示推进,则 f26-51 是**指标失灵**而非真静止。
"""
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

MP4 = "marketing/promo-shotcraft/out/promo-v16.mp4"
W = Path("marketing/promo-shotcraft/out/s1type")
W.mkdir(parents=True, exist_ok=True)
OUT = Path(".tmp/s1-type.txt")

FRAMES = [26, 32, 38, 44, 50, 56]
lines = [
    "=" * 74,
    "S1 打字期 (f26-51) 是否真的在动",
    "=" * 74,
    "",
    "① 无损抽帧(注意:必须用 -pix_fmt rgb24 直接出 PNG,不能走 -q:v 的 JPEG)",
]

paths = {}
for n in FRAMES:
    p = W / f"f{n}.png"
    if not p.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", MP4,
             "-vf", f"select=eq(n\\,{n})", "-vframes", "1", "-pix_fmt", "rgb24", str(p)],
            check=True,
        )
    paths[n] = p
    with Image.open(p) as im:
        lines.append(f"   f{n}: {im.size} {im.format}")

# 副标带:画面垂直中部偏下(品牌字标下方)。取一个横向长条。
def band(p: Path):
    with Image.open(p).convert("L") as im:
        w, h = im.size
        return im.crop((int(w * 0.25), int(h * 0.60), int(w * 0.75), int(h * 0.70)))

lines.append("")
lines.append("② 副标带的「墨迹像素数」(越暗越可能是字)随时间是否增长:")
prev = None
for n in FRAMES:
    b = band(paths[n])
    # 该带均值越低 = 墨迹越多
    m = ImageStat.Stat(b).mean[0]
    d = "" if prev is None else f"   Δ={m - prev:+.3f}"
    lines.append(f"   f{n}: 带内均值 {m:.3f}{d}")
    prev = m

lines.append("")
lines.append("③ 相邻帧在该带的逐像素最大差(>0 = 有像素变化):")
for a, b in zip(FRAMES, FRAMES[1:]):
    diff = ImageChops.difference(band(paths[a]), band(paths[b]))
    st = ImageStat.Stat(diff)
    lines.append(
        f"   f{a}→f{b}: 最大差 {st.extrema[0][1]:3}  平均差 {st.mean[0]:.4f}  "
        f"非零像素占比 {(sum(1 for px in diff.getdata() if px) / (diff.size[0] * diff.size[1])) * 100:.2f}%"
    )

lines.append("")
lines.append("判读:若 ② 单调下降 或 ③ 非零占比明显 >0,则打字期确有推进 ——")
lines.append("      帧差口径把它误判为「静止」,属**指标失灵**,不是真静止。")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
