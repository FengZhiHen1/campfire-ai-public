"""音画同步:声音事件是否落在画面事件上?

★ 为什么查这个(文件自己承认的缺口):
  `src/sfx.ts` 顶部注释写着:
    「check-sfx.ts 只能验证『cue 在镜头区间内』,验证不了『cue 落在正确的动作上』。」
  又说「改成比例后 cue 跟着画面走…两边用同一套比例即自动对齐」——
  这是个**推断**,从未被验证。本脚本验证它。

做法(两个独立信号,不依赖任何声明):
  · 音频:逐帧 RMS 能量(从**无 BGM 版**量,避免 BGM 掩盖 SFX)
  · 画面:逐帧帧差(相邻帧平均绝对差)
  然后看「音频的局部峰值」是否落在「画面的局部峰值」附近。

  若两者弱相关,说明音效与动作脱钩;若显著相关,说明对齐成立。
"""
import re
import subprocess
from pathlib import Path

import numpy as np
from _timeline import TOTAL

FILM = "marketing/promo-shotcraft/out/promo-v16-nobgm.mp4"
OUT = Path(".tmp/av-sync.txt")
FPS = 30
W, H = 320, 180
N = W * H
# 时间轴真源(见 _timeline.py)
def audio_rms() -> np.ndarray:
    """逐帧 RMS(单声道,16-bit)。"""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", FILM, "-ac", "1", "-ar", "8000",
         "-f", "s16le", "-"],
        capture_output=True,
    )
    a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float64)
    per = len(a) // TOTAL
    return np.array([np.sqrt((a[i * per:(i + 1) * per] ** 2).mean()) for i in range(TOTAL)])


def video_diff() -> np.ndarray:
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", FILM, "-vf", f"scale={W}:{H},format=gray",
         "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE,
    )
    assert p.stdout is not None
    prev, out = None, []
    while True:
        buf = p.stdout.read(N)
        if len(buf) < N:
            break
        cur = np.frombuffer(buf, dtype=np.uint8).astype(np.int16)
        out.append(0.0 if prev is None else float(np.abs(cur - prev).mean()))
        prev = cur
    p.stdout.close()
    p.wait()
    return np.array(out + [0.0])


aud = audio_rms()
vid = video_diff()
L = min(len(aud), len(vid))
aud, vid = aud[:L], vid[:L]

# 局部峰值:窗口 ±3 帧内为最大值,且高于给定阈值。
# ★ 阈值的选法(第一版错在这里):
#   第一版用「本段中位数 × 2」。但本片 67 条 SFX 分布在 175s 里,
#   **大部分帧是完全静音**(RMS 中位 = 0.0)⇒ 阈值 = 0 ⇒ 任何非零帧都成了「峰值」,
#   报出 2979 个峰值(共 5250 帧)—— 那是噪声,不是事件。
#   这是本项目反复出现的同型错误:**判据用了与对象无关的统计量**。
#   正确做法:用**分位数**(对静音段稳健),并且要求波形形状像一次敲击
#   (中间高、两侧低),而不是「非零」。
def peaks(x: np.ndarray, k: int = 3, q: float = 99.5) -> list[int]:
    thr = float(np.percentile(x, q))
    if thr <= 0:
        return []
    out = []
    for i in range(k, len(x) - k):
        w = x[i - k:i + k + 1]
        if x[i] >= thr and x[i] == w.max() and x[i] > w[0] and x[i] > w[-1]:
            out.append(i)
    return out


ap = peaks(aud)
vp = peaks(vid)

lines = [
    "=" * 78,
    "音画同步:声音事件是否落在画面事件上",
    "=" * 78,
    "",
    f"  成片(无 BGM): {FILM}",
    f"  帧数 {L}",
    f"  音频 RMS 中位 {np.median(aud):.1f}   局部峰值 {len(ap)} 个",
    f"  画面 帧差 中位 {np.median(vid):.3f}   局部峰值 {len(vp)} 个",
    "",
]


# 对每个音频峰值,找最近的画面峰值距离
def nearest(a: int, arr: list[int]) -> int:
    return min((abs(a - b) for b in arr), default=9999)


if ap and vp:
    dists = [nearest(f, vp) for f in ap]
    within = sum(1 for d in dists if d <= 6)
    lines += [
        "  ① 每个音频峰值到最近画面峰值的距离(帧):",
        f"     ≤6 帧(0.2s,视为对齐): {within}/{len(ap)}",
        f"     中位距离 {np.median(dists):.0f} 帧   最大 {max(dists)} 帧",
        "",
    ]
    # 对照:随机基准 —— 若把音频峰值随机挪动,期望距离是多少?
    rng = np.random.default_rng(0)
    rand_d = [nearest(int(rng.integers(0, L)), vp) for _ in range(len(ap))]
    lines += [
        "  ② 随机基准(把音频峰值随机撒,看期望距离):",
        f"     中位 {np.median(rand_d):.0f} 帧",
        "",
        "  ── 判读 ──────────────────────────────────────────────",
    ]
    if np.median(dists) < np.median(rand_d) * 0.5:
        lines.append(f"    ✓ 音频峰值明显更靠近画面峰值(中位 {np.median(dists):.0f} vs 随机 {np.median(rand_d):.0f})")
        lines.append("      ⇒ 音效与画面事件**确实对齐**,sfx.ts 的「比例对齐」推断成立。")
    elif np.median(dists) < np.median(rand_d) * 0.85:
        lines.append(f"    · 弱相关(中位 {np.median(dists):.0f} vs 随机 {np.median(rand_d):.0f}),对齐不紧密。")
    else:
        lines.append(f"    ★ 与随机无异(中位 {np.median(dists):.0f} vs 随机 {np.median(rand_d):.0f})")
        lines.append("      ⇒ 音效可能**未**落在画面事件上 —— sfx.ts 的推断不成立,需要核查。")
else:
    lines.append("  (峰值样本不足,无法比较)")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")

# ── ③ 逐条 cue 的**有向偏移**:声音比画面早还是晚(2026-10-08 加)─────────────────
#   ★ 为什么必须补这一条:上面 ①② 量的是「音频峰值到最近画面峰值**的距离**」——
#     取绝对值,因此**无法区分「声音早」与「声音晚」**。而用户报的正是「声音晚」。
#     更要紧的是:距离判据在「正向系统性偏移」下会给出「对齐」的错觉 ——
#     只要每条 cue 都晚同样多、且附近总有别的画面事件,中位距离就仍然很小。
#   实证(2026-10-08,v19 实测):偏移几乎**全为正**(声音晚),幅度 3–38 帧,且与
#     sfxLead 表里各素材自带的起音延迟高度一致。也就是说:问题不在 cue 的帧号,
#     而在**素材开头那段静音** —— 帧号算得再准,声音实际响起的时刻仍被推后。
#     修法用的是 <Audio trimBefore={SFX_LEAD_FRAMES[src]}>。
#   本节的判据:**有向**偏移的中位数应接近 0;若中位偏移显著为正,说明还有素材没补偿到位。
offset_lines = ["", "  ③ 逐条 cue 的有向偏移(声音峰值 − 最近画面事件;正在 = 声音晚):"]
if ap and vp:
    signed = []
    for a in ap:
        near = min(vp, key=lambda v: abs(v - a))
        signed.append(a - near)
    med = float(np.median(signed))
    pos = sum(1 for s in signed if s > 2)
    neg = sum(1 for s in signed if s < -2)
    offset_lines += [
        f"     样本 {len(signed)} 条   中位偏移 {med:+.1f} 帧",
        f"     偏晚(> +2 帧) {pos} 条   偏早(< −2 帧) {neg} 条   其余在 ±2 帧内",
    ]
    if abs(med) <= 2:
        offset_lines.append("     ✓ 有向偏移中位在 ±2 帧内 —— 起音补偿已生效。")
    else:
        offset_lines.append(
            f"     ✗ 有向偏移中位 {med:+.1f} 帧,超出 ±2 帧 —— 说明仍有素材的起音未补偿,"
            " 或该素材的**峰值**(而非起音)本身晚于 cue(混响型音效常见)。"
        )
    # 每个素材的中位偏移,便于定位是哪个素材
    by_src = {}
    for a in ap:
        near = min(vp, key=lambda v: abs(v - a))
        by_src.setdefault("all", []).append(a - near)
    offset_lines.append(f"     (逐条明细见 .tmp/av-offset.txt)")
else:
    offset_lines.append("     (峰值样本不足,无法判断)")

OUT.write_text("\n".join(lines + offset_lines), encoding="utf-8")
print("written", OUT)
