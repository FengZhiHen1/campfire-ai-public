"""时间轴真源读取器 —— 所有验证脚本的镜头帧区间都从这里取,不许再各写一份。

★ 为什么需要它(2026-10-07):
  此前 **15 个脚本各自把镜头区间写死**(`TOTAL = 5250`、`("S4", 540, 1500)` …)。
  这在段长不变时看不出问题,一旦 `src/timeline.ts` 的段长变化,它们会**静默量错段** ——
  不报错、只是数字变成别的段的数字。这与本项目反复栽的两类坑同型:
    · 第二真源(timeline.ts 一份、脚本里 15 份);
    · 「检查看起来在跑,实际量的不是它说的东西」。
  所以统一从 `src/timeline.ts` 解析。改段长只需改那一个文件。

用法:脚本直接 `from _timeline import SHOTS, TOTAL, FPS, shot_of`。
（直接运行脚本时 Python 会把脚本所在目录放进 sys.path[0],故同目录 import 可用。）
"""
import pathlib
import re

TIMELINE = pathlib.Path("marketing/promo-shotcraft/src/timeline.ts")


def _parse() -> tuple[int, list[tuple[str, int, int]], int]:
    if not TIMELINE.exists():
        raise SystemExit(
            f"找不到时间轴真源 {TIMELINE} —— 请从仓库根运行,不要猜镜头区间。"
        )
    text = TIMELINE.read_text(encoding="utf-8")
    m = re.search(r"export const FPS\s*=\s*(\d+)", text)
    if m is None:
        raise SystemExit(f"{TIMELINE} 里读不到 FPS —— 拒绝猜。")
    fps = int(m.group(1))
    shots = [
        (mm.group(1), int(mm.group(2)), int(mm.group(3)))
        for mm in re.finditer(r"\{id: '(S\d)', from: (\d+), duration: (\d+)", text)
    ]
    if not shots:
        raise SystemExit(f"{TIMELINE} 里读不到 SHOTS —— 拒绝猜。")
    total = max(frm + dur for _, frm, dur in shots)
    return fps, shots, total


FPS, SHOTS, TOTAL = _parse()

# 便于「按帧反查段名」与「取区间 [from, to)」
BY_ID = {sid: (frm, dur) for sid, frm, dur in SHOTS}
RANGES = [(sid, frm, frm + dur) for sid, frm, dur in SHOTS]


def shot_of(frame: int) -> str:
    for sid, a, b in RANGES:
        if a <= frame < b:
            return sid
    return "?"


def span(shot_id: str) -> tuple[int, int]:
    frm, dur = BY_ID[shot_id]
    return frm, frm + dur
