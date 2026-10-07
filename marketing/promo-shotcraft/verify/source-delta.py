"""判断「重渲是否只改了该改的地方」—— 基于**源码内容哈希**,不是像素差异。

★ 为什么推翻上一版 `ab-diff.py`:
  它拿两版 mp4 逐帧比,把任何 >0.05 的差都当成「改动」。但实测噪声底:
  **同一份源码渲染两次**,mp4 在 329/1200 帧上就有平均 0.044、最大 0.082 的差异
  (H.264 多线程与码率控制决策不是位确定的)。而同样这些帧的**无损 PNG 逐字节相同**。
  于是那个判据把 S5 的纯编码噪声误判成「非预期改动」。

  更根本的问题:**像素 A/B 的分辨率不足以回答这个问题** ——
  S4 的逐字落位修正带来的平均差(0.028~0.069)正好落在噪声带(≤0.09)里。
  所以正确做法是回到**源码层**:列出两个渲染之间到底改了哪些文件,
  再确认每个改动都是预期的。

  这与本项目前三次错误的成因一致:**拿一个分辨率不够的度量去支撑一个它支撑不了的结论。**

★★ P2 重写(2026-10-07)。旧版三处缺陷(均由独立复核指出):

  (a) **文件宇宙对 apps/web 失明**。旧版自己 glob `src/**/*.ts|tsx|json` ⇒
      `apps/web` **0 个**、音频 0 个。而 `src/` 通过 import 依赖 38 个产品文件,
      改产品 `labels.ts` 的可见文案就会改画面 —— P0 那次消融在本脚本里同样抓不到,
      而 DELIVERY.md 却声称它「必须覆盖 apps/web 传递依赖」= **文档承诺 > 实现**。
  → 文件宇宙改为**直接取 `render-manifest.json` 的键**(仓库相对,含
    apps/web 38 / audio 17 / css 8 / config),不再自己 glob。

  (b) **基线靠文件名前缀启发式**。旧版 `startswith("promo-v1")` 会同时匹配
      `promo-v10…promo-v16`,再按 mtime 取最近 ⇒ 名字与时间都不是
      「哪份源码产生了哪版成片」的证据。
  → 改为**比较两份 manifest 的内容哈希**(基线 manifest vs 当前 manifest):
      谁变了、谁新增、谁删除,一目了然,与时钟和命名都无关。

  (c) **找不到基线时 `raise SystemExit(0)`**。交付态下它永远给不出结论,
      却被 DELIVERY.md 当作回答「是不是只改了该改的」的退路。
      一个**在无法作答时判通过**的检查不是检查(AGENTS.md 明令禁止)。
  → 找不到基线 manifest 即 **exit 1**,并打印如何建立基线。

★ 独立复核补的**能力边界**(2026-10-07,已复验,必须连边界一起引用):
  `INTENDED` 是**按路径**登记的,不是按内容。所以在**已登记的路径**里再塞进一处
  未登记改动,只要按本脚本自己的提示重跑 `render-manifest.py`,那个文件就会被记成
  「✓ 预期」而通过。
  ⇒ 本脚本回答的是「**哪些路径变了、这些路径在不在预期清单里**」,
    **不是**「改动内容就是预期的那一句」。要回答后者,必须逐条登记期望的**内容哈希**。
  把这条写进文件头,是因为**夸大一个度量能回答的问题**正是本项目反复出错的模式。

★ 为什么不能只做「基线 manifest vs 当前 manifest 的差异」:
  当前 manifest 是**某次渲染时刻**的快照。若渲染之后源码又被改过,
  两份 manifest 之间的差异**看不到这些新改动**(它们不在任何一份清单里)。
  于是本脚本做**两道**检查,缺一不可:
    ① 漂移:当前 manifest 的每个哈希是否仍等于磁盘上的文件 —— 保证
       「清单描述的源码 = 现在的源码」;
    ② 增量:基线 manifest 与当前 manifest 的差异集,每个都必须在 INTENDED 登记。
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("marketing/promo-shotcraft")
REPO = ROOT.parents[1]

CURRENT = ROOT / "render-manifest.json"
BASELINE_DIR = ROOT / "out" / "baseline"
OUT = Path(".tmp/source-delta.txt")

# ── 本轮的预期源码改动(登记「为什么这个文件该变」) ──────────────
# ★ 只有登记过的差异才算「预期」。没登记的一律计为非预期 ⇒ exit 1。
#   键是**仓库相对**路径(与 render-manifest.json 的键同一坐标系)。
INTENDED: dict[str, str] = {
    "marketing/promo-shotcraft/src/lib/camera.ts":
        "删除 pushCamera 的 sin/cos 周期漂移(方案 A:改语义事件驱动),并清掉死代码 beatPulse",
    "marketing/promo-shotcraft/src/lib/EmergencyFormView.tsx":
        "S4 新增 unselectedDim(勾选后其余 7 项压暗)与 checkedPop(勾选按压回弹)",
    "marketing/promo-shotcraft/src/shots/S2PainPoint.tsx":
        "删往返光带;落位由 sin 描边改单次按压 pop",
    "marketing/promo-shotcraft/src/shots/S3Positioning.tsx":
        "删漂移;两入口由 sin 描边改单次 pop",
    "marketing/promo-shotcraft/src/shots/S4Intake.tsx":
        "删漂移;圈由瞬间出现改 draw-on;接入 unselectedDim/checkedPop",
    "marketing/promo-shotcraft/src/shots/S5Analysis.tsx":
        "删漂移;滚动改刹车;结论行改贴身 accent draw-on",
    "marketing/promo-shotcraft/src/shots/S6ActionCard.tsx":
        "删漂移;徽章 pop;滚动改两次刹车;两节标题下划线 draw-on(序号由数据算)",
    "marketing/promo-shotcraft/src/shots/S7Memory.tsx":
        "删漂移;改三阶推近;拆两幕(档案 15s + 记忆 11s),记忆幕接入 makeMemoryPort",
    "marketing/promo-shotcraft/src/shots/S8Cases.tsx":
        "删漂移;改三阶推近;标签 pop",
    "marketing/promo-shotcraft/src/sfx.ts":
        "S7 拆两幕后重钉 SFX:12 条(含记忆幕 5 条)",
    "marketing/promo-shotcraft/src/fixtures/ports.ts":
        "新增 makeMemoryPort(),读取 memory.generated.ts 的演示种子",
    "marketing/promo-shotcraft/src/fixtures/memory.generated.ts":
        "新增:记忆幕演示种子数据(由 verify/memory-episodes.py export 走产品读路径导出)",
    # ── 以下 9 个是「**闭包新增**,内容未改」,不是源码改动 ──────────
    # S7 拆出记忆幕后,影片首次 import 了产品的记忆功能模块,它们因此
    # 第一次进入清单(基线清单里没有)。证据:这 9 个文件在 git 里**干净**
    # (`git status` 无输出),最后一次改动是 72cff24(2026-10-04),
    # 早于本轮到 v16 的渲染 —— 所以它们不是被这轮改的。
    # 仍然逐条登记,是因为「影片开始依赖它」本身就是画面输入集合的变化,
    # 不该由脚本静默略过。
    "apps/web/src/features/memory/application/ports.ts":
        "闭包新增(内容未改):S7 记忆幕引入的产品记忆功能模块",
    "apps/web/src/features/memory/application/usecases.ts":
        "闭包新增(内容未改):S7 记忆幕引入的产品记忆功能模块",
    "apps/web/src/features/memory/domain/episodes.ts":
        "闭包新增(内容未改):S7 记忆幕引入的产品记忆功能模块",
    "apps/web/src/features/memory/domain/failures.ts":
        "闭包新增(内容未改):S7 记忆幕引入的产品记忆功能模块",
    "apps/web/src/features/memory/domain/formValidation.ts":
        "闭包新增(内容未改):S7 记忆幕引入的产品记忆功能模块",
    "apps/web/src/features/memory/view/MemoryPage.tsx":
        "闭包新增(内容未改):S7 记忆幕的页面本体",
    "apps/web/src/features/memory/view/memoryPage.module.css":
        "闭包新增(内容未改):S7 记忆幕的页面样式(CSS Modules)",
    "apps/web/src/features/memory/viewModel/useMemoryPage.ts":
        "闭包新增(内容未改):S7 记忆幕的 viewModel",
    "apps/web/src/shared/types/memory.ts":
        "闭包新增(内容未改):记忆领域共享类型",
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def resolve(rel: str) -> Path | None:
    """清单键是仓库相对;兼容旧清单的 ROOT 相对写法。"""
    for base in (REPO, ROOT):
        p = base / rel
        if p.exists():
            return p
    return None


# ── 读清单 ─────────────────────────────────────────────────────
if not CURRENT.exists():
    raise SystemExit(f"★ 缺 {CURRENT};先跑 verify/render-manifest.py 重建")

cur = json.loads(CURRENT.read_text(encoding="utf-8"))

base_path: Path | None = None
args = [a for a in sys.argv[1:] if not a.startswith("--baseline-manifest=")]
explicit = [a for a in sys.argv[1:] if a.startswith("--baseline-manifest=")]
if explicit:
    base_path = Path(explicit[0].split("=", 1)[1])
elif BASELINE_DIR.exists():
    cands = sorted(BASELINE_DIR.glob("manifest-*.json"))
    if cands:
        base_path = cands[-1]

if base_path is None or not base_path.exists():
    raise SystemExit(
        "★ 无基线可比 —— 本检查**无法作答**,故判失败(不是通过)。\n"
        f"  期望在 {BASELINE_DIR}/ 下找到 manifest-*.json。\n"
        "  建立基线:重渲前把上一版成片与其清单另存进去,例如\n"
        "    mkdir -p out/baseline\n"
        "    cp out/promo-vNN.mp4 out/baseline/\n"
        "    cp render-manifest.json out/baseline/manifest-vNN.json\n"
        "  也可用 --baseline-manifest=<路径> 显式指定。"
    )

base = json.loads(base_path.read_text(encoding="utf-8"))

# ── ① 漂移:当前清单描述的源码是否仍是磁盘上的源码 ──────────────
drift, gone = [], []
for rel, recorded in cur["files"].items():
    p = resolve(rel)
    if p is None:
        gone.append(rel)
    elif sha(p) != recorded:
        drift.append(rel)

# ── ② 增量:基线 ↔ 当前 ────────────────────────────────────────
bf, cf = base["files"], cur["files"]
added = sorted(k for k in cf if k not in bf)
removed = sorted(k for k in bf if k not in cf)
changed = sorted(k for k in cf if k in bf and cf[k] != bf[k])
delta_all = added + removed + changed
unexpected = [k for k in delta_all if k not in INTENDED]

lines = [
    "=" * 78,
    "重渲是否只改了该改的地方(源码层判据)",
    "=" * 78,
    "",
    f"  基线清单: {base_path}",
    f"     baseline film_sha256 = {base.get('film_sha256', '?')[:24]}…",
    f"  当前清单: {CURRENT}",
    f"     current  film_sha256 = {cur.get('film_sha256', '?')[:24]}…",
    f"  文件宇宙: {len(cf)} 个(取自清单,含 apps/web "
    f"{sum(1 for k in cf if k.startswith('apps/web'))} / audio "
    f"{sum(1 for k in cf if k.endswith('.mp3'))} / css "
    f"{sum(1 for k in cf if k.endswith('.css'))})",
    "",
    "  ① 源码漂移(当前清单的哈希 vs 磁盘现状)",
]
if not drift and not gone:
    lines.append(f"     ✓ 0 处漂移 —— 清单描述的源码就是现在的源码({len(cf)} 个文件)")
else:
    lines.append(f"     ✗ {len(drift)} 个已改动、{len(gone)} 个缺失")
    lines.append("        ⇒ 清单已过期,它不再描述当前源码,也就不能用来论证成片。")
    lines.append("           先重渲并跑 verify/render-manifest.py 重建清单,再谈「只改了该改的」。")
    for f in drift[:20]:
        lines.append(f"        ★ 已改动: {f}")
    for f in gone[:20]:
        lines.append(f"        ★ 缺失  : {f}")

lines += [
    "",
    f"  ② 相对基线的源码差异({len(delta_all)} 个:新增 {len(added)} / "
    f"删除 {len(removed)} / 改动 {len(changed)})",
]
if not delta_all:
    lines.append("     (无差异 —— 两份清单逐哈希相同)")
for f in delta_all:
    mark = "✓ 预期" if f in INTENDED else "★ 非预期"
    lines.append(f"     {mark}  [{('新增' if f in added else '删除' if f in removed else '改动')}] {f}")
    lines.append(f"              {INTENDED.get(f, '(未登记理由)')}")

lines += ["", f"  ③ 非预期改动: {len(unexpected)} 个"]
for f in unexpected:
    lines.append(f"     ★ {f}")

lines += ["", "  ── 结论 ────────────────────────────────────────────────"]
ok = (not drift and not gone and not unexpected)
if ok:
    lines.append("  ✓ 源码层无漂移,且相对基线的每一处差异都已登记理由。")
    lines.append("    **没有非预期改动。**")
else:
    if drift or gone:
        lines.append(f"  ✗ 清单已过期({len(drift) + len(gone)} 个文件与磁盘不符)—— 先重建清单。")
    if unexpected:
        lines.append(f"  ✗ 有 {len(unexpected)} 个非预期改动,需逐个人工确认。")

lines += [
    "",
    "  ── 附带更正:像素 A/B 的分辨率不够 ────────────────────",
    "  噪声底实测(见 verify/encoder-noise.py):",
    "    · 同源双渲 S5:平均差 0.044、最大 0.082(而同样帧的无损 PNG 逐字节相同)",
    "    · S4 逐字落位修正:平均差 0.028~0.069  ← **落在噪声带内,像素法测不出**",
    "    · S8 补两段文字 :平均差 2.85          ← 远超噪声,像素法可见",
    "  所以:像素 A/B 只能发现**大改**,不能用来断言「其他都没变」。",
    "  这个判断必须回到源码层(本脚本),或对**无损 PNG** 逐帧比。",
]

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)

# ★ 非零退出:无法作答(drift/缺基线)与非预期改动都必须卡住流程。
if not ok:
    sys.exit(1)
