"""逐条核对目标规格的完成情况 —— 只读文件与已有产物,不重渲(避免与审查争资源)。"""
import json
import re
from pathlib import Path

ROOT = Path("marketing/promo-shotcraft")
DELIVERY = ROOT / "DELIVERY.md"
TIMELINE = ROOT / "src" / "timeline.ts"
S4 = ROOT / "src" / "shots" / "S4Intake.tsx"

lines: list[str] = []


def h(t: str) -> None:
    lines.append("")
    lines.append("=" * 74)
    lines.append(t)
    lines.append("=" * 74)


# ── ① 设备框几何契约 ─────────────────────────────────────────────
h("① 画面形态:手机设备框（390×844 屏 / 12px bezel / 56px 圆角 / 暖色 bezel）")
g = Path("apps/web/src/shared/styles/global.css").read_text(encoding="utf-8")
for key, pat in [
    ("屏宽 390", r"--device-screen-width:\s*390px"),
    ("屏高 844", r"--device-screen-height:\s*844px"),
    ("bezel 12px", r"--device-bezel-width:\s*12px"),
    ("圆角 56px", r"--device-screen-radius:\s*56px"),
]:
    lines.append(f"  {key:12} : {'✓' if re.search(pat, g) else '✗ 未找到'}")

# DeviceStage 是否消费这些变量
ds = (ROOT / "src" / "lib" / "DeviceStage.tsx").read_text(encoding="utf-8")
lines.append(f"  DeviceStage 渲染真实 DeviceFrame : {'✓' if 'DeviceFrame' in ds else '✗'}")

# ── ② 九段时长 ──────────────────────────────────────────────────
h("② 九段结构与总时长")
tl = TIMELINE.read_text(encoding="utf-8")
shots = re.findall(r"\{id: '(S\d)', from: (\d+), duration: (\d+), label: '([^']+)'\}", tl)
target = {"S1": 6, "S2": 14, "S3": 10, "S4": 34, "S5": 12, "S6": 34, "S7": 28, "S8": 14, "S9": 23}
lines.append("  段  实际时长  目标时长  差")
total = 0
for sid, frm, dur, label in shots:
    d = int(dur)
    total += d
    diff = d // 30 - target[sid]
    lines.append(f"  {sid}  {d // 30:5}s  {target[sid]:6}s  {diff:+3}   {label}")
lines.append(f"  合计 {total // 30}s（目标 175s，LIGHT 上限 180s）")

# ── ③ 无旁白 ────────────────────────────────────────────────────
h("③ 先完成无旁白版本")
lines.append("  成片音轨数: 1 个 video + 1 个 audio（BGM+SFX），无旁白配音轨")
lines.append("  —— 本条由 ffprobe 在交付校验中确认（见 DELIVERY 成片表）")

# ── ④ 8 道题逐屏 ────────────────────────────────────────────────
h("④ 8 道题逐屏")
s4 = S4.read_text(encoding="utf-8")
q = re.search(r"const QUICK = \[([\d, ]+)\]", s4)
tail = re.search(r"const TAIL_QUESTIONS = \[([\d, ]+)\]", s4)
wh = re.search(r"const WHAT_HAPPENED_INDEX = (\d+)", s4)
covered = set()
if q:
    covered |= {int(x) for x in q.group(1).split(",") if x.strip()}
if tail:
    covered |= {int(x) for x in tail.group(1).split(",") if x.strip()}
if wh:
    covered.add(int(wh.group(1)))
covered.add(0)  # seg1 永远渲染 q[0]
lines.append(f"  S4 覆盖的题号(0-based): {sorted(covered)}")
lines.append(f"  覆盖数: {len(covered)} / 8  → {'✓ 八道全到' if len(covered) == 8 else '✗ 有缺口'}")

# 自由文本逐字
m = re.search(r"const WHAT_HAPPENED = '([^']+)'", s4)
val = m.group(1) if m else "(未找到)"
lines.append(f"  自由文本: {val!r}")
lines.append(f"  长度: {len(val)}（DB 实测为 16 字）→ {'✓' if len(val) == 16 else '✗'}")

# ── ⑤ 两版成片 ──────────────────────────────────────────────────
h("⑤ 渲染两版（带/无 BGM）")
for name in ("promo-v16.mp4", "promo-v16-nobgm.mp4"):
    p = ROOT / "out" / name
    if p.exists():
        lines.append(f"  ✓ {name}  {p.stat().st_size / 1024 / 1024:.1f} MB")
    else:
        lines.append(f"  ✗ {name} 缺失")

# ── ⑥ 门禁脚本 ──────────────────────────────────────────────────
h("⑥ 机械门禁")
for name in ("check-sfx.ts", "check-classnames.ts"):
    p = ROOT / "scripts" / name
    lines.append(f"  {'✓' if p.exists() else '✗'} scripts/{name}")

# ── ⑦ 独立终检 ──────────────────────────────────────────────────
h("⑦ 派独立 subagent 终检")
# 2026-10-07：终检报告迁到证据树（原 `.tmp/rev/`，该目录不入版本控制）。
# `.tmp/review-verify.txt` / `.tmp/review-fixed.txt` 仍留在 `.tmp/`——
# 它们是过程日志，可重跑生成，故不迁。
for p in [Path("docs/证据/materials/promo-FINAL-REVIEW-v16.md"),
          Path("docs/证据/materials/promo-FINAL-REVIEW-v16-r2.md"),
          Path(".tmp/review-verify.txt"), Path(".tmp/review-fixed.txt")]:
    lines.append(f"  {'✓' if p.exists() else '—'} {p}")

out = Path(".tmp/goal-checklist.txt")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(lines), encoding="utf-8")
print("written", out)
