"""先验证检测器本身,再拿它量东西。

★ 三次失败的原因(全部是「判据与对象不匹配」):
    v1 每行暗像素 ≥5         → 检出**文字**(设备缩小后左右 bezel 各仅约 2.6px)
    v2 连续暗像素 ≥50 @480p  → 各切点都报「无设备」(缩放+抗锯齿把 bezel 稀释了)
    v3 中心窄条+每行≥20      → 仍把文字行当设备(报「S1 设备高 36px」,那是两行字)

★ 正确签名:设备的**上/下 bezel 是两条长约 380px 的水平暗条**(设备外宽 414px)。
   在 1920 原分辨率下,文字行最长不过约 140px ⇒ 只要要求「连续暗像素 ≥250px」,
   文字就不可能命中。这是把「连续长度」当作判据,而不是「暗像素数量」。

本脚本先用**已知答案的帧**校验检测器,通过了才继续。校验样本:
  · f1000 (S4 表单页,应有设备)
  · f296  (S2 满幅排版,应无设备)
  · f4930 (S8 案例库,应有设备)
"""
import subprocess
from pathlib import Path

import numpy as np

FILM = "marketing/promo-shotcraft/out/promo-v16.mp4"
OUT = Path(".tmp/detector-validated.txt")
W, H = 1920, 1080
N = W * H
DARK = 100
MIN_RUN = 250     # px:设备的上下 bezel 横条约 380px;文字行最长约 140px

# 已知答案的校验样本 (帧, 是否应有设备框)
SAMPLES = [(1000, True), (296, False), (4930, True), (60, False), (2000, True)]


def longest_run(row: np.ndarray) -> int:
    best = cur = 0
    for v in row:
        if v:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


def device_span(a: np.ndarray) -> tuple[int, int] | None:
    runs = np.array([longest_run(r) for r in (a < DARK)])
    bars = np.where(runs >= MIN_RUN)[0]
    if bars.size < 2:
        return None
    return int(bars[0]), int(bars[-1])


# 读需要的帧
want = sorted({f for f, _ in SAMPLES})
p = subprocess.Popen(
    ["ffmpeg", "-v", "error", "-i", FILM, "-vf", "format=gray", "-f", "rawvideo", "-"],
    stdout=subprocess.PIPE,
)
assert p.stdout is not None
got = {}
i = 0
while True:
    buf = p.stdout.read(N)
    if len(buf) < N:
        break
    if i in want:
        got[i] = np.frombuffer(buf, dtype=np.uint8).reshape(H, W)
    i += 1
p.stdout.close()
p.wait()

lines = [
    "=" * 78,
    "检测器校验(先证明仪器可靠,再拿它量东西)",
    "=" * 78,
    "",
    f"  参数:灰<{DARK},连续暗像素 ≥{MIN_RUN}px",
    "",
    "  帧      期望      实测",
]
ok = True
for f, expect in SAMPLES:
    a = got.get(f)
    if a is None:
        lines.append(f"  f{f}: 未读到")
        ok = False
        continue
    span = device_span(a)
    actual = span is not None
    mark = "✓" if actual == expect else "★ 不符"
    if actual != expect:
        ok = False
    detail = f"上{span[0]} 下{span[1]} 高{span[1]-span[0]}" if span else "未检出"
    lines.append(f"  f{f:<6} {'有设备' if expect else '无设备':8}  {detail:24} {mark}")

lines += [
    "",
    f"  校验结果: {'✓ 检测器可信,可以拿它量切点' if ok else '★ 检测器仍不可信,不应据它下结论'}",
]
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
