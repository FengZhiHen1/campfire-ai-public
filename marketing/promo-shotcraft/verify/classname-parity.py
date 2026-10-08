"""逐条核对:影片的手写复刻(EmergencyFormView)是否与真实页面用了同一套契约类名。

动机:skill final-review D3 要求「表现真实产品页面时使用真实截图,而非手搓复刻」。
本片因**帧驱动**的技术约束无法直接用真实页面(实测:它的 index/handled 是 useState,
不同帧渲染出完全相同的画面,见 .tmp/rf2-* 的 SHA256 相同),所以走的是「复用产品
契约类名 + 产品 CSS」的复刻路线。

那么「是否忠实」就必须**机械核对**,不能靠「我看着一样」。本项目已因此出过一次错:
复刻里曾用 `step-forward` / `handled-note` 这两个**产品里不存在**的类名
(产品用的是 CSS Module 的 styles.stepForward / styles.handledNote)。

本脚本:列出真实页面用的类名 → 检查复刻里也用了 → 反向列出复刻里的类名是否都真实存在。
"""
import re
from pathlib import Path

REAL = Path("apps/web/src/features/consult/view/EmergencyFormPage.tsx")
FILM = Path("marketing/promo-shotcraft/src/lib/EmergencyFormView.tsx")
OUT = Path(".tmp/classname-parity.txt")


def classes_of(text: str) -> set[str]:
    """抽出 className 里的字面量类名(忽略 CSS Module 的 styles.xxx)。"""
    found: set[str] = set()
    for m in re.finditer(r'className=(?:"([^"]+)"|\{`([^`]+)`\})', text):
        raw = m.group(1) or m.group(2) or ""
        # 去掉模板插值
        raw = re.sub(r"\$\{[^}]*\}", " ", raw)
        for tok in raw.split():
            if tok and not tok.startswith("styles."):
                found.add(tok)
    return found


real_src = REAL.read_text(encoding="utf-8")
film_src = FILM.read_text(encoding="utf-8")
real = classes_of(real_src)
film = classes_of(film_src)

lines = [
    "=" * 74,
    "影片复刻 vs 真实页面 —— 契约类名逐条核对",
    "=" * 74,
    f"  真实页面 (EmergencyFormPage.tsx) : {len(real)} 个类名",
    f"  影片复刻 (EmergencyFormView.tsx) : {len(film)} 个类名",
    "",
    "① 真实页面用了、影片复刻**也用了**的(应当占多数):",
]
shared = sorted(real & film)
lines.append(f"  {len(shared)} 个: {' '.join(shared)}")

lines.append("")
lines.append("② ★ 真实页面用了、但影片复刻**没用**的:")
miss = sorted(real - film)
if miss:
    for c in miss:
        lines.append(f"    {c}")
else:
    lines.append("    (无)")

lines.append("")
lines.append("③ ★★ 影片复刻用了、但**真实页面没有**的(潜在自造类名,风险最高):")
extra = sorted(film - real)
if extra:
    for c in extra:
        lines.append(f"    {c}")
else:
    lines.append("    (无)")

lines.append("")
lines.append("判据:③ 里若出现「看起来像产品类名但不存在的」条目,即为自造类名 ——")
lines.append("      那种类名不会命中任何产品 CSS,元素会退回浏览器默认外观(静默错版)。")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
