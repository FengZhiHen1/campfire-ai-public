import subprocess
from pathlib import Path
from PIL import Image

MP4 = "marketing/promo-shotcraft/out/promo-v16.mp4"
W = Path("marketing/promo-shotcraft/out/sticky8")
W.mkdir(parents=True, exist_ok=True)
out = []
for n in (4570, 4650, 4750, 4850, 4930):
    p = W / f"f{n}.png"
    if not p.exists():
        subprocess.run(["ffmpeg","-y","-loglevel","error","-i",MP4,
                        "-vf",f"select=eq(n\\,{n}),crop=420:120:430:180",
                        "-vframes","1","-pix_fmt","rgb24",str(p)], check=True)
    im = Image.open(p).convert("L")
    px = im.load()
    w,h = im.size
    rows = [y for y in range(h) if sum(1 for x in range(w) if px[x,y] < 150) >= 3]
    first = rows[0] if rows else None
    last = rows[-1] if rows else None
    out.append(f"  f{n}: 页头墨迹行 y={first}..{last}")
Path(".tmp/sticky8.txt").write_text(chr(10).join(out), encoding="utf-8")
print(chr(10).join(out))
