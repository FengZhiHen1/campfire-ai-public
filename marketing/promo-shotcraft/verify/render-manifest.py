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

IMPORT_RE = re.compile(r"""(?:^|\n)\s*import\s+(?:type\s+)?[^'"]*?from\s*['"]([^'"]+)['"]""")
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
    # ★ 把音频资源也纳入(见 audio_assets 的说明:漏收录 = 门禁失明)
    files |= audio_assets()
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
    film = ROOT / "out" / "promo-v16.mp4"
    m = {
        "film": "out/promo-v16.mp4",
        "film_sha256": sha(film).upper() if film.exists() else None,
        "note": ("本清单由 verify/render-manifest.py 从入口的 **import 闭包**推导"
                 "(含 apps/web 传递依赖),并纳入 **public/audio 全部音频资源**;"
                 "不是手写白名单。凡在此列表内,改动都必须重渲(或先用无损 PNG 消融证明)。"),
        "derived_from": "src/index.ts",
        "counts": {"total": len(entries), "apps_web": n_web, "audio": n_audio},
        "files": entries,
    }
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"清单已推导:{len(entries)} 个文件"
          f"(apps/web {n_web} 个,音频 {n_audio} 个)")
    print(f"成片: {m['film_sha256']}")


main()
