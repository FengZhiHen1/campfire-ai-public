"""从 import 图**推导**渲染相关文件,而不是手写白名单。

★★ 为什么重写(独立复核 P0,已消融证实):
  旧版只 glob `src/**`,于是 manifest 里 **37 个条目全是 src/、apps/web 条目 0 个**。
  但 `src/` 通过 import 依赖 **17 处**产品文件(`DeviceFrame`、`ActionCard`、
  `HomePage`、`domainLabel`、`EMERGENCY_QUESTIONS`、类型定义…)。
  复核者做了决定性消融:把产品 `labels.ts` 的 `owner: '项目所有者核准'` 改成
  `'XX-ABLATION-XX'`(画面上可见的文案)→ **画面 SHA 变了**,
  而 `doc-consistency.py` 仍报「0 处不一致 / 37 个文件一致」。
  **⇒ 一个能改画面的文件被改,两道门禁全绿。**

  这正是 S8 那条修复本身所走的链路 —— 我用一个对 `apps/web` 失明的清单,
  去证明「我改的正是我声称改的那些文件」。

修法:从入口文件出发 BFS 解析相对 import,把**传递依赖闭包**全部纳入。
      凡不在闭包里的文件,改它确实不影响画面;在闭包里的,改它就必须重渲。
"""
from __future__ import annotations

import json
import re
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # marketing/promo-shotcraft
REPO = ROOT.parents[1]                              # 仓库根
ENTRY = ROOT / "src" / "index.ts"
MANIFEST = ROOT / "render-manifest.json"

# ★★ P0 修复(2026-10-07,见 CHECKPOINT.md §3):旧正则要求 `from`,
#   于是 DeviceStage.tsx 引入 4 个产品 CSS 的**副作用 import**(无 from):
#     import '../../../../apps/web/src/shared/styles/tokens.css';
#   一条都匹配不到 ⇒ 清单对「样式」这一整类输入失明 —— 改 tokens.css
#   能改变画面,而门禁仍报「82 个文件一致 / 0 处不一致 / exit 0」。
#   现已消融证实并修复:`from` 子句改为可选,副作用 import 同样纳入闭包。
IMPORT_RE = re.compile(
    r"""(?:^|\n)\s*import\s+(?:type\s+)?(?:[^'"]*?\sfrom\s*)?['"]([^'"]+)['"]"""
)
CSS_IMPORT_RE = re.compile(r"""@import\s+['"]([^'"]+)['"]""")
EXTS = ["", ".ts", ".tsx", ".css", ".json", "/index.ts", "/index.tsx"]


def resolve(spec: str, from_file: Path) -> Path | None:
    if spec.startswith("."):
        base = (from_file.parent / spec).resolve()
    elif spec.startswith("../../") or spec.startswith("../"):
        base = (from_file.parent / spec).resolve()
    else:
        return None            # 裸包名(node_modules)不算项目源码
    for e in EXTS:
        p = Path(str(base) + e)
        if p.is_file():
            return p
    return None


def closure() -> set[Path]:
    """从入口出发的传递依赖闭包(含 CSS/@import)。"""
    seen: set[Path] = set()
    q = deque([ENTRY])
    while q:
        f = q.popleft()
        if f in seen or not f.is_file():
            continue
        seen.add(f)
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        specs = IMPORT_RE.findall(text)
        if f.suffix == ".css" or "@import" in text:
            specs += CSS_IMPORT_RE.findall(text)
        for s in specs:
            r = resolve(s, f)
            if r is not None and r not in seen:
                q.append(r)
    return seen


def build_config() -> set[Path]:
    """构建期配置 —— 会改渲染行为,必须纳入。

    ★★ 又一类被我漏掉的输入(第 6 轮收尾自查):
      `remotion.config.ts` 决定编码器、并发、图片格式、`--gl` 等;
      `package.json` 决定 remotion 版本。改它们会改变成片,而 import 闭包看不见。

    ★ P0 补充(2026-10-07):纳入**视觉契约真源** `docs/design/tokens.css`。
      `apps/web/scripts/sync-tokens.mjs` 声明它是「视觉契约唯一权威」,
      apps/web 侧的 tokens.css 只是它的复制产物 —— 改真源并重新同步
      就能改变画面,而它此前不在清单里(正是 P0 消融所用的文件)。
      少收录的代价是「多比一个文件」,漏收录的代价是「门禁失明」,不对称。

    ★ 反过来,`public/textures/**` **不**纳入 —— 我做过**真消融**验证:
      把整个 `public/textures` 移走后渲染同一帧,SHA256 不变
      (`909394CBA3B6111ED741`)。它只是**旧截图路线的遗留素材**,
      现在只在一条注释里被提到(见 DeviceStage.tsx 的说明)。
      ⚠ 第一次做这个消融时我用 `Rename-Item` 但**它失败了**,
      于是两次渲染比对的是同一个文件系统状态 —— 「相同」是假的。
      改用 `Move-Item` 并**校验目录确实不在原位**后,结论才成立。
    """
    out: set[Path] = set()
    for name in ("remotion.config.ts", "remotion.config.js", "package.json"):
        p = ROOT / name
        if p.is_file():
            out.add(p)
    tokens = REPO / "docs" / "design" / "tokens.css"
    if tokens.is_file():
        out.add(tokens)
    return out


def audio_assets() -> set[Path]:
    """成片用到的**音频资源**。

    ★★ 自查发现的缺口(第 6 轮修完 manifest 之后):
      import 闭包只覆盖代码 —— 但成片还有音轨,而音轨由 `public/audio/**` 决定。
      我第一版「修好」的清单里有 63 个 .ts/.tsx/.css/.json,**音频 0 个**。
      换个 `public/audio/sfx/*.mp3` 就能改变成片,而门禁不会响 ——
      与 P0 是**同一个失败模式**(清单对某一整类依赖失明),只是换了一类。

      做法:不去解析 `staticFile('…')` 的字符串拼接(那是脆的),
      而是**把 public/audio 下全部资源都纳入** —— 少收录的代价是「多比几个文件」,
      漏收录的代价是「门禁失明」,两者不对称,所以宁可全收。
    """
    base = ROOT / "public" / "audio"
    if not base.is_dir():
        return set()
    return {p for p in base.rglob("*") if p.is_file()}


def sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    files = closure()
    # ★ 把音频资源与构建期配置也纳入(见各自函数的说明:漏收录 = 门禁失明)
    files |= audio_assets()
    files |= build_config()
    if "--list-outsiders" in sys.argv:
        # 列出「在 src/ 下但不在闭包内」的文件 —— 它们改了确实不影响画面
        all_src = {p for p in (ROOT / "src").rglob("*")
                   if p.is_file() and p.suffix in (".ts", ".tsx", ".css", ".json")
                   and "probe" not in p.parts}
        outside = sorted(str(p.relative_to(ROOT)).replace("\\", "/")
                         for p in all_src - {f for f in files if str(f).startswith(str(ROOT))})
        print(f"不在渲染闭包内的 src 文件({len(outside)} 个,改它们不影响画面):")
        for o in outside:
            print("   ", o)
        return

    entries = {}
    for f in sorted(files):
        # ★ 路径基准必须**统一**,否则同一份清单里混两种前缀
        #   (src/... 与 marketing/promo-shotcraft/...),统计与比对都会出错 ——
        #   audio 计数曾因此为 0(条目其实在,只是前缀不同)。
        #   统一规则:能相对仓库根就相对仓库根,否则相对影片项目根。
        try:
            rel = f.relative_to(REPO)
        except ValueError:
            rel = f.relative_to(ROOT)
        entries[str(rel).replace("\\", "/")] = sha(f)

    n_web = sum(1 for k in entries if k.startswith("apps/web"))
    n_audio = sum(1 for k in entries if "/public/audio/" in k or k.startswith("public/audio/"))
    n_css = sum(1 for k in entries if k.endswith(".css"))
    # ★★ P0 自检(2026-10-07,与「apps/web 条目为 0 就报错」同型):
    #   影片显式 import 了 4 个产品 CSS,又纳入 1 个视觉契约真源 ⇒ CSS 条目至少 5 个。
    #   若为 0,说明样式解析又坏了(最可能:副作用 import 没被匹配)——
    #   一个对样式失明的清单正是 P0 的失败模式,宁可报错也不假通过。
    if n_css < 5:
        sys.stderr.write(
            f"[render-manifest] CSS entries = {n_css} (< 5) — style layer blind, "
            "side-effect imports not parsed? refusing to write manifest\n"
        )
        sys.exit(1)
    # ★ 2026-10-07:成片名不再写死。旧版硬编 `out/promo-v16.mp4`;重渲出 v17 之后
    #   它仍指 v16,于是清单会同时记录「v17 的源码哈希」与「v16 的成片哈希」——
    #   一份**自相矛盾**的记录(本次实测踩到)。判据改为:取 out/ 下最新的
    #   `promo-v<数字>.mp4`(显式排除 -nobgm 与 out/baseline/,后者是基线存档)。
    films = [p for p in (ROOT / "out").glob("promo-v*.mp4")
             if re.fullmatch(r"promo-v\d+\.mp4", p.name)]
    if not films:
        sys.stderr.write(
            "[render-manifest] no out/promo-v<N>.mp4 found — refusing to guess which film "
            "this manifest describes\n"
        )
        sys.exit(1)
    film = max(films, key=lambda p: p.stat().st_mtime)
    m = {
        "film": f"out/{film.name}",
        "film_sha256": sha(film).upper(),
        "note": ("本清单由 verify/render-manifest.py 从入口的 **import 闭包**推导"
                 "(含 apps/web 传递依赖与副作用 CSS import);另**手工补入两组**"
                 "非 import 输入:① public/audio 下全部音频资源;② 视觉契约真源 "
                 "docs/design/tokens.css(该路径**硬编在脚本里**)。"
                 "★ 独立复核指出:原先写的「不是手写白名单」**只对 import 闭包那部分成立** ——"
                 "这两组是手写的,漏加一个文件,门禁就会对它失明(P0 的失败模式)。"
                 "凡在此列表内,改动都必须重渲(或先用无损 PNG 消融证明)。"),
        "derived_from": "src/index.ts",
        "counts": {"total": len(entries), "apps_web": n_web, "audio": n_audio,
                   "css": n_css},
        "files": entries,
    }
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest derived: {len(entries)} files "
          f"(apps/web {n_web}, audio {n_audio}, css {n_css})")
    print(f"film: {m['film']} {m['film_sha256']}")


main()
