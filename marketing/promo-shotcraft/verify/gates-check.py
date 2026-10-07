"""核对影片在 S5 讲的「六层闸门」是否与产品真源一致。

产品真源: apps/api/skills/emergency-consulting/references/gates.md
影片在画面(右侧说明区)与流式文本里都提到「六层闸门」。若层数或顺序与产品不符,
那是**事实性错误**,不是风格问题。
"""
import re
from pathlib import Path

OUT = Path(".tmp/gates-check.txt")
gates = Path("apps/api/skills/emergency-consulting/references/gates.md")

lines = ["=" * 74, "「六层闸门」与产品真源的核对", "=" * 74]

text = gates.read_text(encoding="utf-8")
# 抽出一级/二级标题里的层名
heads = re.findall(r"^#{2,3}\s*(.+)$", text, re.M)
lines.append("")
lines.append(f"  真源 {gates}")
lines.append(f"  文件内标题 {len(heads)} 条:")
for h in heads[:14]:
    lines.append(f"    {h.strip()}")

# SKILL.md 里的顺序描述
skill = Path("apps/api/skills/emergency-consulting/SKILL.md").read_text(encoding="utf-8")
i = skill.find("六层闸门")
lines.append("")
lines.append("  SKILL.md 里「六层闸门」附近的描述:")
lines.append("    " + " ".join(skill[max(0, i - 40):i + 320].split()))

# 影片里怎么说
s5 = Path("marketing/promo-shotcraft/src/shots/S5Analysis.tsx").read_text(encoding="utf-8")
stream = Path("marketing/promo-shotcraft/src/fixtures/stream.generated.ts").read_text(encoding="utf-8")
lines.append("")
lines.append("  影片里出现的「六层闸门」:")
for src_name, t in (("S5Analysis.tsx", s5), ("stream.generated.ts", stream)):
    for m in re.finditer(r".{25}六层闸门.{25}", t):
        lines.append(f"    [{src_name}] …{m.group(0)}…")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
