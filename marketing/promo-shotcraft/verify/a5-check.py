"""A5 复核:凡被影片使用的**长样本(>5s)**,是否都显式给了 durationInFrames。

final-review A5 原文:「长样本(>5s,库里 21 个)是否都显式给了 durationInFrames,
有没有音效拖到动作结束后还在响」。
关键是「被使用的」长样本 —— 库里没用到的长样本不需要处理。
"""
import json
import re
import subprocess
from pathlib import Path

REPO = Path(".")
SFX_DIR = REPO / ".dsh" / "skills" / "video-shotcraft" / "assets" / "audio" / "sfx"
FILM = REPO / "marketing" / "promo-shotcraft"
OUT = Path(".tmp/a5-check.txt")

# 库里的长样本
long_samples: dict[str, float] = {}
for p in SFX_DIR.rglob("*"):
    if p.suffix.lower() not in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
        continue
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    try:
        d = float(r.stdout.strip())
    except ValueError:
        continue
    if d > 5:
        long_samples[p.stem] = round(d, 2)

# 影片用到的条目
src = (FILM / "src" / "sfx.ts").read_text(encoding="utf-8")
entries = re.findall(
    r"\{from: at\('(S\d)', ([\d.]+)\), src: '([^']+)', volume: ([\d.]+)"
    r"(, durationInFrames: (\d+))?",
    src,
)
used = {e[2] for e in entries}

lines = [
    "=" * 74,
    "A5 复核：被使用的长样本(>5s)是否都显式给了 durationInFrames",
    "=" * 74,
    f"  库里长样本(>5s): {len(long_samples)} 个",
    f"  影片 SFX 条目  : {len(entries)} 条",
    f"  影片用到的素材  : {len(used)} 种",
    "",
    "① 被影片使用的长样本:",
]
bad = []
for e in entries:
    name = e[2]
    if name not in long_samples:
        continue
    has_dur = e[5] is not None
    mark = "✓ 有 durationInFrames" if has_dur else "✗ 缺失!"
    if not has_dur:
        bad.append(name)
    lines.append(f"   {e[0]} {e[1]}  {name} ({long_samples[name]}s)  {mark}")

if not any(e[2] in long_samples for e in entries):
    lines.append("   (被使用的素材里没有长样本)")

lines.append("")
lines.append("② 未被使用的长样本(无需处理，仅列出):")
unused_long = sorted(set(long_samples) - used)
lines.append(f"   {len(unused_long)} 个: {', '.join(unused_long[:12])}"
             + (" …" if len(unused_long) > 12 else ""))

lines.append("")
lines.append(f"结论: {'✓ 所有被使用的长样本都显式截断了' if not bad else '✗ 缺失: ' + ', '.join(bad)}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
