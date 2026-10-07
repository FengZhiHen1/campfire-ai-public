"""盘点影片的「景别分级」实际做到了哪几级。

目标①原文:「手机设备框 + **元素级特写分级**」。
这个要求是为**截图路线**写的 —— 那条路线里「特写」= 把某个元素按 2x 切出来放大到满屏。
本片改为组件渲染后,可实现的特写手段不同,必须如实盘点**实际有哪几级**,
而不是含糊地说「做到了」。

本脚本从源码机械统计每一段用了哪些景别手段。
"""
import re
from pathlib import Path

ROOT = Path("marketing/promo-shotcraft/src/shots")
OUT = Path(".tmp/framing-levels.txt")

SHOTS = ["S1BrandOpen", "S2PainPoint", "S3Positioning", "S4Intake", "S5Analysis",
         "S6ActionCard", "S7Memory", "S8Cases", "S9Closing"]

lines = [
    "=" * 78,
    "景别分级盘点（机械统计，不靠印象）",
    "=" * 78,
    "",
    "  段              设备框  相机推近  元素强调  纯排版段  说明",
]

for name in SHOTS:
    t = (ROOT / f"{name}.tsx").read_text(encoding="utf-8")
    device = "有" if "DeviceStage" in t else "—"
    push = "有" if ("pushCamera" in t or "stagedPush" in t) else "—"
    # 元素强调:用 CSS 选择器命中真实元素(::after / outline / drop-shadow 之类)
    emphasis = "有" if re.search(r"::after|outline|dropShadow|drop-shadow", t) else "—"
    # 纯排版段:整段没有设备框
    typo = "整段" if "DeviceStage" not in t else "—"
    note = ""
    if name in ("S1BrandOpen", "S9Closing"):
        note = "品牌/边界:满屏排版"
    elif name == "S2PainPoint":
        note = "痛点:满屏排版(暗场)"
    elif name == "S6ActionCard":
        note = "seg0 是纯排版三档特写,seg1+ 才是设备"
    lines.append(
        f"  {name:16} {device:6} {push:8} {emphasis:8} {typo:8} {note}"
    )

lines.append("")
lines.append("  四级景别的**实际对应**:")
lines.append("    L1 满屏排版   —— S1/S2/S9,以及 S6 的 seg0(三档语义特写)")
lines.append("    L2 设备框全景 —— S3-S8 的默认景别(390×844 屏完整可见)")
lines.append("    L3 设备框推近 —— 相机 scale 1.16-1.20(仍在框内,细节更清)")
lines.append("    L4 元素强调   —— CSS 命中**真实元素**(S3 两张入口卡 / S7「确认」按钮 /")
lines.append("                     S8「虚构样例」标签),元素自身描边+光晕")
lines.append("")
lines.append("  ★ 没有实现的一级:把某个元素切出来**满屏放大**(截图路线的 2x cutout)。")
lines.append("    原因:本片渲染真实组件,`transform` 缩放由浏览器矢量重绘,")
lines.append("    已无模糊问题;而「单独把按钮放大到满屏」需要把该元素从页面里摘出来渲染,")
lines.append("    那会同时丢掉它的上下文(周边留白、与相邻元素的关系)——")
lines.append("    而这恰恰是用户前三轮反馈里反复要求的(「不要平铺」「别框错位置」)。")
lines.append("    **因此这是有意取舍,不是遗漏。**")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
