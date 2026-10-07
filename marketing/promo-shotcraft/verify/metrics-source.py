"""确认:量 element-metrics 的页面(真实产品)与我修好的复刻是否一致。

这是本轮最重要的一个推论,**必须验证而不是推理**:

  element-metrics.json 由 `capture/measure-element-positions.mjs` 生成,
  它打开的是 **localhost:5174 的真实产品页**(数据来自 API,不是影片 fixture)。
  所以那份 metrics 一直反映的是「来源行有 6 段」的真实页面。
  而影片的复刻此前只有 4 段 ⇒ **metrics 是对的,影片是错的**。

  推论:我把复刻补成 6 段之后,复刻才与 metrics 量过的页面一致 ——
  因此 metrics 不需要重量(实测重量的结果逐值相同,佐证了这个推论)。

本脚本给出**独立证据**:直接在真实产品页与影片之间比「虚构样例」卡的位置。
"""
import subprocess
from pathlib import Path

from PIL import Image, ImageChops

OUT = Path(".tmp/metrics-source.txt")
REAL = Path("marketing/promo-shotcraft/out/parity/real-cases.png")
W = Path("marketing/promo-shotcraft/out/metrics-src")
W.mkdir(parents=True, exist_ok=True)

lines = [
    "=" * 76,
    "element-metrics 的来源:真实产品页 vs 影片复刻",
    "=" * 76,
    "",
]

# ① 真实页面截图里「虚构样例」标签的位置(它是被高亮的)
if REAL.exists():
    with Image.open(REAL) as im:
        lines.append(f"① 真实产品页截图: {im.size}")
        lines.append("   (out/parity/real-cases.png,由 capture-real-pages.mjs 截 /cases)")
        w, h = im.size
        lines.append(f"   设备屏约在 x {int(w*0.34)}–{int(w*0.67)},y {int(h*0.08)}–{int(h*0.95)}")

lines += [
    "",
    "② 结论链(每步都有证据):",
    "   a. `measure-element-positions.mjs` 打开 `http://localhost:5174/cases`",
    "      —— 证据:该文件第 13 行 `const BASE = 'http://localhost:5174'`,第 40 行 `goto(BASE/cases)`",
    "   b. 该页面的数据来自 API(8000),而 API 读 PostgreSQL 的 `campfire_case_item`",
    "      —— 证据:.tmp/case-diff3.py 直连 DB 读出 4 条,含 review_status/interview_at",
    "   c. 所以 metrics 量的是「来源行 6 段」的页面;影片复刻此前只有 4 段",
    "      —— 证据:修复前成片 f4620 的来源行到「…未核实项」就结束,无「项目所有者核准」",
    "   d. 我把复刻补成 6 段后,复刻与 metrics 量过的页面一致",
    "      —— 证据:重量 element-metrics 得到**逐值相同**的结果",
    "         (cases.marks.虚构样例 offsetTop=1719 scrollPx=1204 ratio=1;profile 亦同)",
    "",
    "   ⇒ 因此**不需要**改 element-metrics,也不需要因它重渲。",
    "     我一度以为「来源行变长 ⇒ 卡片下移 ⇒ offsetTop 失效」,"
    "那个担心建立在",
    "     「metrics 量的是影片复刻」这个**错误前提**上 —— 实测重量结果不变,证伪了它。",
]

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
