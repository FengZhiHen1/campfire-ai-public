"""最直接的检验:每条**声明的 SFX cue** 处,画面是否比随机帧更「有事发生」?

★ 为什么换成这个问法:
  前两版都试图「各自找峰值再比距离」,结果两次都被阈值绑架:
    ① 用「中位×2」→ 静音段使阈值=0 → 报 2979 个音频峰值(噪声)
    ② 用 99.5 分位 + 严格局部极大 → 只剩 8 个音频、6 个画面峰值(过严)
  两次都在**调阈值**,而正确做法是**绕开峰值检测**:
  直接问「在 sfx.ts 声明的那些帧上,画面活动量是否高于全片随机帧」。

  如果音效确实钉在画面事件上,那么 cue 帧的画面帧差应显著高于随机帧。

做法:
  · 从 src/sfx.ts 解析出全部 cue 的**绝对帧**(按 timeline 把比例换算)
  · 从成片量逐帧画面帧差
  · 比较 cue 帧的帧差分布 vs 随机帧的帧差分布(Mann-Whitney 式的简单判读)
"""
import re
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path("marketing/promo-shotcraft")
SFX = (ROOT / "src" / "sfx.ts").read_text(encoding="utf-8")
TL = (ROOT / "src" / "timeline.ts").read_text(encoding="utf-8")
FILM = str(ROOT / "out" / "promo-v16-nobgm.mp4")
OUT = Path(".tmp/cue-activity.txt")
W, H = 320, 180
N = W * H
FPS = 30

# ── 段表 ──
shots = {}
for m in re.finditer(r"\{id: '(S\d)', from: (\d+), duration: (\d+)", TL):
    shots[m.group(1)] = (int(m.group(2)), int(m.group(3)))

# ── cue:形如 at('S4', 0.13) 或 shot('S4').from + ... ──
cues = []
for m in re.finditer(r"at\('(S\d)',\s*([\d.]+)\)", SFX):
    sid, ratio = m.group(1), float(m.group(2))
    if sid in shots:
        base, dur = shots[sid]
        cues.append((sid, ratio, base + int(round(ratio * dur))))
# 也统计一下有没有非比例的写法残留
legacy = len(re.findall(r"shot\('S\d'\)\.from\s*\+", SFX))

# ── 画面逐帧帧差 ──
p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", FILM, "-vf", f"scale={W}:{H},format=gray",
     "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert p.stdout is not None
prev, diff = None, []
while True:
    buf = p.stdout.read(N)
    if len(buf) < N:
        break
    cur = np.frombuffer(buf, dtype=np.uint8).astype(np.int16)
    diff.append(0.0 if prev is None else float(np.abs(cur - prev).mean()))
    prev = cur
p.stdout.close()
p.wait()
d = np.array(diff + [0.0])

lines = [
    "=" * 78,
    "每条 SFX cue 处的画面活动量 vs 全片随机帧",
    "=" * 78,
    "",
    f"  从 sfx.ts 解析到 cue {len(cues)} 条(比例写法);非比例写法残留 {legacy} 处",
    f"  段表 {len(shots)} 段",
    "",
]
if not cues:
    lines.append("  ★ 未解析到 cue —— 检查 sfx.ts 的写法是否变了")
else:
    cue_d = np.array([d[min(f, len(d) - 1)] for _, _, f in cues])
    all_d = d[1:]
    lines += [
        f"  cue 帧的画面帧差: 中位 {np.median(cue_d):.3f}  均值 {cue_d.mean():.3f}  "
        f"最大 {cue_d.max():.3f}",
        f"  全片随机帧      : 中位 {np.median(all_d):.3f}  均值 {all_d.mean():.3f}  "
        f"最大 {all_d.max():.3f}",
        "",
        f"  比值(cue 均值 / 全片均值): {cue_d.mean() / all_d.mean():.2f}×",
        "",
        "  判读:",
    ]
    r = cue_d.mean() / all_d.mean()
    if r >= 1.5:
        lines.append(f"    ✓ cue 处的画面活动量是全片均值的 {r:.2f} 倍")
        lines.append("      ⇒ 音效**确实**钉在画面事件上,sfx.ts 的「比例对齐」推断成立。")
    elif r >= 1.15:
        lines.append(f"    · cue 处活动量偏高({r:.2f}×),但不够显著,对齐较松。")
    else:
        lines.append(f"    ★ cue 处活动量与全片随机帧无差别({r:.2f}×)")
        lines.append("      ⇒ 音效位置与画面事件**无关**,需要核查 sfx.ts 的 cue。")

    # 逐条列出活动量最低的 cue —— 那些最可能「响在没有动作的地方」
    lines += ["", "  活动量最低的 10 条 cue(最可能响在无动作处):"]
    order = np.argsort(cue_d)
    for i in order[:10]:
        sid, ratio, f = cues[int(i)]
        lines.append(f"    {sid} 比例 {ratio:<6} 绝对帧 {f:<5} ({f/FPS:6.2f}s)  "
                     f"帧差 {cue_d[int(i)]:.3f}")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
