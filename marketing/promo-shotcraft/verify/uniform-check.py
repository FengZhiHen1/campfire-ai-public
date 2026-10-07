"""找「完全均匀帧」—— 用 PIL 直接量每帧像素标准差,不依赖 ffmpeg 的 YSTD。

为什么值得单独查:整帧只有一个颜色的画面 = 观众看到一片空白。
终检在上一版报过 6 个 std=0 帧(含 f0)。本片已修 f0 与 S2 开头,这里做全片确认。

★★ 2026-10-07 三处修复(独立复核指出,已实测确认):
  (1) **零结果被当成通过** —— 旧版在抽帧数为 0 时输出
      「抽帧数: 0 / 标准差 < 0.5 的帧: 0」并 **exit 0**。
      复核实测:清空 `out/uniform/` 后只留 `done.flag` 即复现。这正是 AGENTS.md
      禁止的「永远不会失败的检查」。现在零帧直接非零退出。
  (2) **没有结论闸门** —— 旧版只是**打印**「标准差 < 0.5 的帧: N」,N>0 也 exit 0。
      本脚本存在的唯一目的就是找这种帧;找到却不失败等于没查。现在 N>0 即 exit 1。
  (3) **抽帧缓存不记「抽的是哪一版」** —— `done.flag` 只写 "ok"。换一版成片后
      缓存不失效,脚本会继续量**旧成片**的帧(与 README 陷阱 12 同型:
      「读不到/读到旧的」被当成「现在什么都没有」)。
      现在 flag 里记录成片 sha256,不一致就重抽。

另:成片名不再写死(旧版硬编 `promo-v16.mp4`,重渲后它会静默地继续量旧成片)。
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageStat

ROOT = Path("marketing/promo-shotcraft")
# 取 out/ 下最新的 promo-v<N>.mp4(排除 -nobgm 与 out/baseline/)
_films = [p for p in (ROOT / "out").glob("promo-v*.mp4")
          if re.fullmatch(r"promo-v\d+\.mp4", p.name)]
if not _films:
    raise SystemExit("no out/promo-v<N>.mp4 found -- refusing to guess which film to measure")
MP4 = max(_films, key=lambda p: p.stat().st_mtime)
FILM_SHA = hashlib.sha256(MP4.read_bytes()).hexdigest()

WORK = ROOT / "out" / "uniform"
WORK.mkdir(parents=True, exist_ok=True)
FLAG = WORK / "done.flag"
OUT = Path(".tmp/uniform-check.txt")

# 逐帧抽小图(160x90)以便覆盖全片又不爆磁盘;均匀性与分辨率无关。
# ★ flag 必须记录成片指纹:否则换版后缓存不失效,量的是旧成片的帧。
if not FLAG.exists() or FLAG.read_text(encoding="utf-8").strip() != FILM_SHA:
    for old in WORK.glob("f*.png"):
        old.unlink()
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(MP4),
         "-vf", "scale=160:90", "-an", str(WORK / "f%05d.png")],
        check=True,
    )
    FLAG.write_text(FILM_SHA, encoding="utf-8")

files = sorted(WORK.glob("f*.png"))
# ★★ 零结果 = 失败,不是「均匀帧 0 个」。没有帧就没有测量,不能判通过。
if not files:
    raise SystemExit(
        f"no frames extracted from {MP4} -- do NOT read this as 'no uniform frames'.\n"
        f"  ({WORK/'done.flag'} 记的是 {FLAG.read_text(encoding='utf-8')[:12]}…)"
    )

lines = [
    "=" * 74,
    "完全均匀帧检查(整帧只有一个颜色 = 空画面)",
    "=" * 74,
    f"  成片  : {MP4}",
    f"  抽帧数: {len(files)}",
]
uniform = []
lowest = []
for p in files:
    n = int(p.stem[1:]) - 1          # ffmpeg 从 1 开始编号
    st = ImageStat.Stat(Image.open(p).convert("L"))
    sd = st.stddev[0]
    if sd < 0.5:
        uniform.append(n)
    lowest.append((sd, n))

lines.append(f"  标准差 < 0.5 的帧: {len(uniform)}")
if uniform:
    lines.append("  位置:")
    for f in uniform[:12]:
        seg = ("S1" if f < 120 else "S2" if f < 300 else "S3" if f < 540
               else "S4" if f < 1500 else "S5" if f < 2700 else "S6" if f < 3780
               else "S7" if f < 4560 else "S8" if f < 4950 else "S9")
        lines.append(f"    f{f} → {seg}")

lowest.sort()
lines.append("")
lines.append("  标准差最低的 10 帧:")
for sd, n in lowest[:10]:
    seg = ("S1" if n < 120 else "S2" if n < 300 else "S3" if n < 540
           else "S4" if n < 1500 else "S5" if n < 2700 else "S6" if n < 3780
           else "S7" if n < 4560 else "S8" if n < 4950 else "S9")
    lines.append(f"    f{n:5} (成片) {seg}  std={sd:.3f}")

lines.append("")
lines.append("  判据:std < 0.5 视为「视觉上与空白无异」。")
lines.append("")
lines.append("  结论:" + ("★ 0 帧均匀 —— 通过" if not uniform
                          else f"★ 有 {len(uniform)} 帧均匀 —— **不合格**"))
OUT.write_text("\n".join(lines), encoding="utf-8")
# ★ stdout 只打英文:终端是 GBK,报告里的 ★/→ 等字符一旦不在 GBK 内会直接抛
#   UnicodeEncodeError,看起来像「检查发现了问题」,实际是编码崩了(见 README 陷阱 15)。
print("written", OUT)

if uniform:
    sys.exit(1)
