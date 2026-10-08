"""核对:影片画面上声称的「七节分区」是否与真实行动卡一致。

这属于**画面上的事实断言**,必须逐字核对 —— 本项目在类似的地方出过错
(S4 注释曾把 8 项写成「九项」)。用 card_id 精确定位那张卡再数。
"""
import json
import re
from pathlib import Path

ROOT = Path("marketing/promo-shotcraft")
DATA = ROOT / "src" / "fixtures" / "data.generated.ts"
OUT = Path(".tmp/s6-count.txt")

text = DATA.read_text(encoding="utf-8")

# 用影片注释里给的 card_id 精确定位
CARD_ID = "b6b1f07c461f459d898f93555d910643"
lines = [
    "=" * 74,
    "行动卡分区数核对（画面声称「七节分区」）",
    "=" * 74,
    f"  目标 card_id: {CARD_ID}",
]

i = text.find(CARD_ID)
if i < 0:
    lines.append("  ✗ fixture 里找不到这个 card_id")
else:
    # 从 card_id 往后找该卡的 sections 数组
    j = text.find('"sections"', i)
    # 手动配对括号取到该数组结尾
    k = text.find("[", j)
    depth = 0
    end = k
    for pos in range(k, min(len(text), k + 60000)):
        if text[pos] == "[":
            depth += 1
        elif text[pos] == "]":
            depth -= 1
            if depth == 0:
                end = pos
                break
    arr = text[k:end + 1]
    keys = re.findall(r'"key":\s*"([a-z_]+)"', arr)
    heads = re.findall(r'"heading":\s*"([^"]+)"', arr)
    lines.append(f"  该卡 sections 条数: {len(keys)}")
    for n, (kk, hh) in enumerate(zip(keys, heads), 1):
        lines.append(f"    {n}. {kk:20} {hh}")
    lines.append("")
    verdict = "✓ 与画面声称一致" if len(keys) == 7 else f"✗ 画面说 7 节，实际 {len(keys)} 节"
    lines.append(f"  画面声称「七节分区」→ {verdict}")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
