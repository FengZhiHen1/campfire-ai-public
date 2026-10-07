"""音效素材的静音头盘点 + 与 cue 语义的关系。

★ 起因:`cue-onsets.py` 报 S5 f1530 的 cue 附近完全没有音频。
  追查发现**不是 cue 放错位置**,而是**素材本身有静音头**:
    data-stream.mp3 前 0.4s 是数字静音(RMS 恰好 0),0.4s 后才起;
    另有 sparkle.mp3 前 0.35s 均值 −62.7 dB(很轻)。

★ 为什么这不是缺陷(但要记录):
    这两条都是**氛围/光效**类素材,不是点事件:
      · data-stream  注释是「S5『正在分析』底噪」—— 底噪本就该渐入
      · sparkle      是光效,渐入反而更自然
    对它们,缓起是**素材的正确用法**;若强行要求「cue 帧即刻可闻」,
    反而会得到一个突兀的爆音。

★ 但有一个**真需要知道**的后果:
    如果某条 cue 的语义是**点事件**(impact/lock/snap 类),而素材又有静音头,
    那声音就会比画面事件晚 0.4s —— 那才是失配。
    本脚本据此把「有静音头的素材」× 「被当作点事件使用」的交叉情况列出来。
"""
import re
import subprocess
from pathlib import Path

ROOT = Path("marketing/promo-shotcraft")
SFX = (ROOT / "src" / "sfx.ts").read_text(encoding="utf-8")
OUT = Path(".tmp/silent-head.txt")

# ① 每条素材前 0.5s 的能量
heads = {}
for p in sorted((ROOT / "public" / "audio" / "sfx").glob("*.mp3")):
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(p), "-t", "0.5",
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore",
    )
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr + r.stdout)
    heads[p.stem] = float(m.group(1)) if m else None

# ② 每条 cue 用的素材与语义(注释)
cues = []
for m in re.finditer(
    r"\{from: at\('(S\d)',\s*([\d.]+)\),\s*src: '([^']+)',\s*volume: ([\d.]+)([^}]*)\}",
    SFX,
):
    sid, ratio, src, vol, rest = m.groups()
    cm = re.search(r"comment: '([^']*)'", rest)
    cues.append((sid, float(ratio), src, float(vol), cm.group(1) if cm else ""))

# ③ 点事件词(语义上要求「立刻可闻」)
POINT_WORDS = ("切入", "命中", "落定", "敲", "锁", "弹出", "转场", "提交", "翻",
               "点击", "按下", "到达", "爆发", "起手")

QUIET = -45.0   # 前 0.5s 均值低于此视为「有静音头/很轻」

lines = [
    "=" * 78,
    "音效素材的静音头 vs cue 语义",
    "=" * 78,
    "",
    "  ① 各素材前 0.5s 平均音量(越低 = 起得越慢):",
]
for k, v in sorted(heads.items(), key=lambda kv: (kv[1] if kv[1] is not None else 0)):
    flag = "  ★ 静音头/很轻" if (v is not None and v < QUIET) else ""
    lines.append(f"     {k:22} {v:7.1f} dB{flag}")

lines += ["", f"  ② 用「有静音头」素材、且注释像**点事件**的 cue(这些才可能失配):"]
risky = []
for sid, ratio, src, vol, cm in cues:
    hv = heads.get(src)
    if hv is not None and hv < QUIET and any(w in cm for w in POINT_WORDS):
        risky.append((sid, ratio, src, cm))
if risky:
    for sid, ratio, src, cm in risky:
        lines.append(f"     {sid} 比例 {ratio:<6} {src:16} 「{cm}」")
else:
    lines.append("     (无)")

lines += ["", "  ③ 用「有静音头」素材、但注释是**氛围/光效**的 cue(缓起是正确用法):"]
ok = []
for sid, ratio, src, vol, cm in cues:
    hv = heads.get(src)
    if hv is not None and hv < QUIET and not any(w in cm for w in POINT_WORDS):
        ok.append((sid, ratio, src, cm))
for sid, ratio, src, cm in ok:
    lines.append(f"     {sid} 比例 {ratio:<6} {src:16} 「{cm}」")

lines += [
    "",
    "  ── 结论 ──────────────────────────────────────────────",
]
if not risky:
    lines.append("    ✓ **没有**「点事件用了带静音头的素材」的情况 ⇒ 不存在音画失配。")
    lines.append("      检测到的那条『哑 cue』(S5 f1530, data-stream 底噪)属于氛围素材,")
    lines.append("      缓起是素材的正确用法,不必修。")
else:
    lines.append(f"    ★ 有 {len(risky)} 条点事件用了带静音头的素材 ⇒ 声音会比画面晚约 0.4s,建议修。")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
