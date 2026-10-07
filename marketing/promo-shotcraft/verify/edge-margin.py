"""测量 S5 推近到最大时设备框与画布上下边的间隙。

判据:终检说 f2660 上间隙 4px、下间隙 2px —— 太贴边。这里直接量中间列的深色像素范围。
"""
import subprocess
from pathlib import Path

MP4 = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/edge-margin.txt")
lines: list[str] = []


def grab(n: int) -> Path:
    p = Path("marketing/promo-shotcraft/out/edgechk")
    p.mkdir(parents=True, exist_ok=True)
    f = p / f"m{n}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", MP4,
         "-vf", f"select=eq(n\\,{n})", "-vframes", "1", str(f)],
        check=True,
    )
    return f


try:
    from PIL import Image  # type: ignore

    for n in (2400, 2500, 2560, 2620, 2660, 2690):
        im = Image.open(grab(n)).convert("RGB")
        w, h = im.size
        px = im.load()
        # 取 x 在设备水平中心附近的列(设备居中于 x≈640 的画布坐标;成片 1920 宽)
        col = 640
        # 找该列上第一个/最后一个「非纸色」像素。纸色大约 (247,241,232) 附近,
        # 用「明显更暗」作为判据(bezel 是深暖色)
        top = bottom = None
        for y in range(h):
            r, g, b = px[col, y]
            if max(r, g, b) < 150:          # 深色 = bezel
                if top is None:
                    top = y
                bottom = y
        lines.append(f"f{n}: 设备框上边 y={top}  下边 y={bottom}  "
                     f"上间隙={top}  下间隙={h - 1 - (bottom or 0)}")
except ImportError:
    lines.append("缺 PIL")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written")
