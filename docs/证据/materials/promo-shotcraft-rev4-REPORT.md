# 独立复核报告(rev4)— 对「第 6 轮 5 项修复」的验证

工作目录 `E:\Project\Web_Development\Campfire-AI`,复核时间 2026-10-07 09:50–10:35。
所有脚本与中间产物在 `marketing/promo-shotcraft/.tmp/rev4/`。**未修改仓库任何源文件**
(两处消融改动均已还原,`git diff` 为空)。

> **重要前提:目标在复核期间被并发修改。**
> `render-manifest.py` / `render-manifest.json` / `DELIVERY.md` / `ROUND_STATE.md` 在我
> 开始后陆续被改(mtime 10:01:04 / 10:01:14 / 10:01:29,即复核进行中)。
> 我据此**钉了一份快照** `.tmp/rev4/snapshot/`,下文所有结论都标注了它针对的是快照还是
> 最终状态。**这不影响任何判定** —— 见下文,关键缺陷在快照与最终状态里都存在。

## 结论汇总(按严重度)

| # | 项 | 判定 |
|---|---|---|
| **P0** | `render-manifest.json` 对**样式层**完全失明 | **不成立(修复未完成)** |
| **P1** | `bezel-scan.py` 在「扫到帧但一个段都没命中」时仍报 9999px / exit 0 | **部分修复** |
| **P2** | `source-delta.py` 的文件宇宙**不含 `apps/web`**,且基线判据会选中过期成片 | **不成立(修复未完成)** |
| P3 | `doc-consistency.py` 对不一致能非零退出 | **成立** |
| P3 | `s5-recheck.py` 输出真实数字、缺文件非零退出 | **成立** |
| P3 | `bezel-scan.py` 默认路径 / 缺文件非零退出 | **成立** |
| P4 | 时间戳 `Z` 进了成片 | **成立** |
| P4 | 摘要行取首个内容节点 | **成立** |
| P4 | 文档残留 `+00:00` 旧值(与同文件新值矛盾) | **新发现** |
| P5 | 「渲染有极小非确定性」 | **无法复现(84 次全同)** |
| P5 | 「同源双渲 H.264 会不同」 | **成立(但我实测的幅度远大于其报告值)** |

---

## ① P0 — `render-manifest.json` 对样式层失明(决定性消融)

### 缺陷
`DocStage.tsx:23-29` 用**副作用式 import**引入产品样式:

```ts
import '../../../../apps/web/src/shared/styles/tokens.css';
import '../../../../apps/web/src/shared/styles/global.css';
import '../../../../apps/web/src/shared/styles/components.css';
import '../../../../apps/web/src/features/consult/view/consultComponents.css';
```

`render-manifest.py:31` 的 `IMPORT_RE` 要求 **`... from '...'`**:

```python
IMPORT_RE = re.compile(r"""(?:^|\n)\s*import\s+(?:type\s+)?[^'"]*?from\s*['"]([^'"]+)['"]""")
```

副作用 import 没有 `from`,**正则一条都匹配不到**。`resolve()` 里对 `../../` 的兜底分支
写了也白写 —— 根本没走进 `specs`。该正则对**任何**无 `from` 的 import 都失明
(`import 'x.css'`、`import 'side-effect-module'`),不只是 CSS。

### 差集(独立重实现闭包 vs 官方清单)
`.tmp/rev4/closure-audit.py`(我自己的解析器,额外抓 `import '...'` / `import()` /
`require()` / `export ... from`):

```
在我的闭包内、不在官方清单(4 个):
    apps/web/src/features/consult/view/consultComponents.css
    apps/web/src/shared/styles/components.css
    apps/web/src/shared/styles/global.css
    apps/web/src/shared/styles/tokens.css

无法解析的相对 import 写法(4 条):
    MISSED-BY-OFFICIAL:.../DeviceStage.tsx :: ../../../../apps/web/src/shared/styles/tokens.css -> apps/web/src/shared/styles/tokens.css
    MISSED-BY-OFFICIAL:.../DeviceStage.tsx :: ../../../../apps/web/src/shared/styles/global.css  -> apps/web/src/shared/styles/global.css
    MISSED-BY-OFFICIAL:.../DeviceStage.tsx :: ../../../../apps/web/src/shared/styles/components.css -> apps/web/src/shared/styles/components.css
    MISSED-BY-OFFICIAL:.../DeviceStage.tsx :: ../../../../apps/web/src/features/consult/view/consultComponents.css -> apps/web/src/features/consult/view/consultComponents.css
```

### 消融(照上一轮复核者的方法,改画面可见的 CSS 变量)
把 `tokens.css` 的 `--accent: #c2410c;`(火焰橙)改成 `#0c41c2;`:

```
基线 f400 (未改) : F437CA153D91CCEE48AB2E334033FCB1EEC28A2E0525965053224CDDAF8B4E3A
消融 f400 (改后) : A82577FB488FC52F39458902B46475A1A21C3A10364AB2E125B0252193F7CF50
```

**画面变了。** 此时跑门禁:

```
$ uv run python marketing/promo-shotcraft/verify/doc-consistency.py
  ✓ 成片对应的源码内容未变（逐文件 sha256 比对，含 apps/web 传递依赖）
      82 个文件一致（其中 apps/web 34 个；非 mtime 判据）
  ✓ 清单覆盖产品代码（apps/web 条目数 > 0）
      apps/web 条目 34 个
  共 0 处不一致
[EXITCODE=0]
```

**全绿 + exit 0。连同 10:01 新增的「构建配置 2 个」一起,仍然抓不到。**

### 阳性对照(证明门禁不是整体失效)
把**在清单内**的 `labels.ts` 的 `owner: '项目所有者核准'` 改成 `'XX-ABLATION-XX'`:

```
  ✗ 成片对应的源码内容未变（逐文件 sha256 比对，含 apps/web 传递依赖）
      ★ 有 1 个已改动、0 个缺失
      ★ 已改动: apps/web/src/features/library/domain/labels.ts
  共 1 处不一致
[EXITCODE=1]
```

**⇒ 门禁机制本身是好的,失明的是「样式这一整类输入」。**
这与上一轮被抓的 P0 **是同一个失败模式**(对一整类依赖失明),只是从「产品 TS 代码」
换成了「产品 CSS」。作者在 `DELIVERY.md:228-230` 自己写下
「要问的不是『还漏了哪个文件』,而是『成片由哪几类输入决定』—— 代码、样式、数据、音频、字体…」
—— **示例里的「样式」正好就是当下失明的那一类。**

### 附带发现:`docs/design/tokens.css` 也是真源
`apps/web/scripts/sync-tokens.mjs` 声明 `docs/design/tokens.css` 是
**视觉契约唯一权威**(复制到 `apps/web/src/shared/styles/tokens.css`)。
改 `docs/design/tokens.css` 后跑一次 `pnpm --filter @campfire/web dev/build`
(或手工 sync)就会改画面,而**这两个文件都不在清单里**。

### 字体类:未发现缺口,但作者的理由不严谨
仓库内(git 跟踪范围)**没有任何 `.woff/.woff2/.ttf/.otf` 文件**,CSS 链里也
**没有 `@font-face` / 网络 `@import`**(我 grep 过 4 个 CSS)。所以「改字体文件改画面」
在当前实现下**不可达** —— 这一点作者是对的。
但 `render-manifest.py:80-86` 说「`public/textures/**` 不纳入(已用真消融证明)」:
我核实 `public/textures/**`(73 张图)确实**没有任何代码引用**
(只有 `DeviceStage.tsx:4` 的一条注释提到 `<Img src="textures/...">`)。
所以结论对,但**它的安全性依赖于「没有引用」这个脆弱事实**,而不是清单机制本身。

### 路径基准与重复项:干净
- 非统一前缀条目:**0**;绝对路径条目:**0**;`counts` 与 `len(files)` 一致。
- 同名文件 3 组(`ports.ts` / `usecases.ts` / `failures.ts`),但都是**真实不同的文件**
  (library vs profile),不是同一文件两种前缀。**无重复记账问题。**

---

## ② P1 — 门禁的「非零退出」

### `doc-consistency.py`:✅ 成立
不一致时 `exit 1`(见上阳性对照)。一致时 `exit 0`。**这是真门禁。**

### `s5-recheck.py`:✅ 成立
逐字照 `ACCEPTANCE.md` 跑(见「二、机械门禁」表里没有列它;我按 `ROUND_STATE.md:88` 的命令跑):

```
  ① 静止率(口径:320×180 + tblend 帧差,YAVG < 0.35)
     全片: 8.9%
     S5  : 2.6%
  ② 边距
     扫描帧数: 5250
     全片最小边距: 11px
[EXITCODE=0]
```
缺文件时(在 `.tmp/rev4/` 下跑,相对路径失效):
`★ 找不到成片: marketing\promo-shotcraft\out\promo-v16.mp4` → **`exit 1`**。
**「S5 静止率 0.0%」已不再出现,真实数字是 2.6%。**

### `bezel-scan.py`:⚠️ 部分修复(残留一个「永不失败」的出口)
缺文件 / 非视频文件:✅ 非零退出
```
$ bezel-scan.py marketing/promo-shotcraft/package.json
★ 扫不到任何帧(...package.json)—— 不要把它当成通过。
[EXITCODE=1]
```

**但**:给一个**能解码、但一个段都没命中**的成片,判据仍然静默通过:

```
$ bezel-scan.py marketing/promo-shotcraft/out/s1seg.mp4      # S1 品牌段,无设备框,120 帧
  扫描帧数: 120
  S3     9999px    fNone      ...
  ...
  全片最小边距: 9999px
[EXITCODE=0]        ← 与上一轮被抓的旧行为**完全一样**
```

原因:`fidx` 被 `fidx += 1` 每帧无条件递增 ⇒ `if fidx == 0` 的守卫**永远不触发**;
而 `per_frame` 收集的是**全片**深色像素,`s1seg` 有深色文字 ⇒ 守卫放行;
`mins[sid]` 只有「命中该段区间且检出深色」才更新,否则保留哨兵 **9999**,
且输出里没有哨兵检查。**这正是上一轮复核者逐字照跑得到的那个输出。**

复现命令:
```powershell
uv run python marketing/promo-shotcraft/verify/bezel-scan.py marketing/promo-shotcraft/out/s1seg.mp4
```
（`out/` 内仍留有 `s1seg/s2seg/s5seg/...` 等分段 mp4;此路径是脚本自己文件头里
「用法: <成片路径>」所鼓励的用法。对默认的全片 `promo-v16.mp4`,输出正确。)
影响有限,但按 AGENTS.md「禁止留下永远不会失败的检查」,**这个出口应收紧**
(命中 0 段的段应为失败,或对 `mins` 里的哨兵显式报错)。

`motion-fresh.py` 的守卫经我实测是**真的**会触发(我一次误用相对路径踩到):
`未采到任何 YAVG —— 不要把它当成「静止率 0%」` → `exit 1`。✅

---

## ③ P4 — 两处保真修正:✅ 两处都进了成片

### 时间戳 `Z`
`campfire_case_item.interview_at` 真实值(直连 DB):

| title | `interview_at` |
|---|---|
| 成年才被看见… | `2026-05-31T00:50:00+00:00` |
| 从不定期炸弹… | `2026-05-30T14:43:00+00:00` |
| 从强迫到尊重… | `2026-05-25T06:48:00+00:00` |
| 虚构样例… | `2026-11-06T02:00:00+00:00` |

产品 wire 格式(Pydantic)为 `…Z`。**成片 f4935 的虚构样例卡末段实测显示
`访谈 2026-11-06T02:00:00Z`**(我裁到 5 倍放大逐字确认,见 `.tmp/rev4/ts-4935.png`)。
**✅ 与声称一致。**

### 摘要行取首个内容节点
DB 规则复核:`data_campfire_node` 中 `metadata_->>'library'='case'` 共 27 行,
每条的 `node_id` 形如 `<uuid>:card:0|card:1|narrative:0…` —— **字符串序 == 语义序**,
所以 `DISTINCT ON (item_id) ORDER BY node_id` 与产品 `_first_node_summary()` 同规则。

推出 `141d3b9f…` 的摘要 = `title：冷处理+自主外出空间策略应对情绪爆发 - ASD成人愤怒行为管理\nscenario：适用于 ASD 成人…` ——
**成片 f4620 实测显示 `title：冷处理+自主外出空间策略应对情绪爆发 - ASD 成人愤怒行为管理 scenario：适用于 ASD 成人因日常挫…`**。
fixture(`data.generated.ts:260`)与 DB 逐字一致,**不再是重复标题**。**✅ 成立。**

### 另外查的保真偏差
- **来源行段数:6 段齐 ✅。** 我一度在低分辨率缩略图上数成 5 段(误判),裁到原分辨率后
  确认是 **6 段**:`来源：…(长句)` + `专家访谈转写` + `机构材料`(虚构卡为 `观察性经验`)
  + `项目所有者核准` + `授权句` + `访谈 …Z`。与 `itemMetaParts()` 口径一致。
- **状态标签 ✅**:DB `status` = `fictional` ×1 / `internal` ×3,成片虚构卡标「虚构样例」、
  其余标「内部」,与 DB 一致。
- **列表页首屏 ✅**:真实页 `out/parity/real-cases.png` 有搜索框 + `案例/资料` 分页签,
  成片 f4570 同样有。逐项对上。

### ⚠️ 新发现:文档内两处残留**与同文件新值矛盾的旧时间戳**
| 位置 | 内容 |
|---|---|
| `ACCEPTANCE.md:278` | 「成年才被看见卡显示「…访谈 2026-05-31T00:50:00**+00:00**」;虚构样例卡显示「…访谈 2026-11-06T02:00:00**+00:00**」」 |
| `DELIVERY.md:151` | 「成片复核已见「项目所有者核准…访谈 2026-05-31T00:50:00**+00:00**」」 |

而 `DELIVERY.md:214`(第 31 条表项)写的是「重渲后成片已见 **`Z`**」。
**同一份文档,一条说 `Z`、一条说 `+00:00`,两处都声称是「成片复核」。**
按文档自己的规矩,`ACCEPTANCE.md:278` 与 `DELIVERY.md:151` 是**第 4 轮**的历史记录,
可以保留当时的值 —— 但它们的措辞是「**成片复核**」(现在时的事实断言),而不是
「当轮实测」,而 `DELIVERY.md:155` 对同类情况**明确采用了「保留当轮实测值 + 加注」的写法**。
**处理不一致,且后者可被读成当前事实。建议加注或改为「当时实测」。**

---

## ④ P2 — `source-delta.py` 的基线逻辑

### (a) 「报无基线并 exit 0」是否恰当?—— **方向对,但落地成了净损失**
当前 `out/` 下唯一 `is_full` 为真的文件是 `promo-v16-nobgm.mp4`(09:47:52),
而它是**同一次交付的姊妹版,不是上一版**,所以不早于当前成片 ⇒ 无候选。
脚本输出「⚠ 无基线可比」+ `exit 0`。

「不编造结论」本身是对的方向(旧版拿已删文件的 mtime 硬算更糟)。
但结果是:**文件头声称的「替代像素 A/B 的源码层判据」在交付态下永远给不出结论**,
而 `DELIVERY.md:405` 把这个脚本当作「回答『是不是只改了该改的』」的唯一退路。

### (b) 判据会选错文件 —— **实证**
```python
if p.name.startswith("promo-v16") or p.name.startswith("promo-v1"):
    ... 时长 ≈175.019 ...
```
`startswith("promo-v1")` 把 `promo-v2.mp4` / `promo-v2-nobgm.mp4` 也算进来。
实测(我的 `.tmp/rev4/delta-universe.py`):

```
被名字前缀判据排除掉的「全片」成片(对照):
    promo-v2-nobgm.mp4  duration=175.019  ← 时长符合「全片」,但因前缀不匹配被排除
    promo-v2.mp4        duration=175.019  ← 时长符合「全片」,但因前缀不匹配被排除
```

理由也站不住:「`promo-v1` 前缀」是想捞 `promo-v16*`,但 `promo-v16*` 已被前一个
条件覆盖,这个分支**只**捞到了 `promo-v10..v14`(全为 145s ⇒ 被时长判据挡掉)
和 `promo-v2`(175.019s ⇒ **通过**)。若把当前成片换成 `promo-v2.mp4`,
`max(prev, key=mtime)` 会选中 **`promo-v16-nobgm.mp4`(09:47)** 作为「v2 的上一版」,
而它**晚于 v2 三天**、且是**完全不同的内容** ⇒ `changed_after_cut` 会把
`promo-v2` 之后**全部**源码改动都算成「本次重渲引入」。

### (c) 更根本:文件宇宙**不含 `apps/web`**
我复刻脚本自己的 `mtimes()`:

```
扫描到的文件数: 37
其中 apps/web 路径数: 0
其中落在 apps/web 下的条目: (无 —— apps/web 完全不在扫描范围内)
是否包含 P0 消融用的那个文件 apps/web/src/features/library/domain/labels.ts ? **否**

glob 模式: ("src/**/*.ts", "src/**/*.tsx", "src/**/*.json")   # 相对 promo-shotcraft/
```

⇒ **P0 那条消融(改 `labels.ts` 可见文案)在这个脚本里同样抓不到。**
而 `DELIVERY.md:405` 却写「必须覆盖 `apps/web` 传递依赖 —— 见第九节 P0」,
**文档声称它有这个覆盖,实际没有**。这是「文档承诺 > 实现」的一处。

**小结**:第 4 项修复**未完成**。要它成立,至少需要:① 文件宇宙改为从
`render-manifest.json`(修好样式层之后)驱动,而不是自己 glob `src/**`;
② 基线判据改用时长(去掉脆弱的名字前缀),或直接要求显式传入基线。

---

## ⑤ P5 — 「渲染有极小非确定性」:我**无法复现**

作者在 `DELIVERY.md:216` / `ACCEPTANCE.md:361-378` / `ROUND_STATE.md:47-52` 采纳了
前一位复核者的论断,并据此把因果写成
**「渲染本身有极小的非确定性(0.012%/单行),H.264 的帧间预测把它按 GOP 放大」**。
我按指示自己做了不少于 10 次同帧重复渲染:

### 单帧 `remotion still`,f1500 × **16 次**
```
distinct hashes: 54F8AFA0AD2FABDD x16
```
**16/16 逐字节相同。**

### 单帧 `remotion render --sequence --image-format=png`(复核者声称的方法)
| 帧 | 次数 | 结果 |
|---|---|---|
| **f997**(复核者点名的帧) | **14** | `D64229F1A9B0D519…` ×14,**全部相同** |
| f1500 | 14 | `54F8AFA0AD2FABDD…` ×14,**全部相同** |

### 该区间的「地毯式」重渲(复核者称 f1497–1505 附近有子像素抖动)
| 帧 | 次数 | distinct |
|---|---|---|
| 1497 | 8 | **1** |
| 1499 | 8 | **1** |
| 1500 | 8 | **1** |
| 1501 | 8 | **1** |
| 1503 | 8 | **1** |
| 1505 | 8 | **1** |

### 区间内(有上下文、并发 8)双渲 900–1100,逐帧比 201 帧
```
same=201  diff=0
```

**累计 100+ 次同帧渲染(其中 f997 两次独立实验各 14 次,合计 28 次),
未观察到任何一次变体。** 对 `promo-v16` 的确定性,我**不能确认**它有问题。

### 但「H.264 编码不是位确定的」我**确认成立**,且幅度明显
同一区间(1500–1699,`--concurrency=1 --crf=18`)渲两次:

| | runa.mp4 | runb.mp4 |
|---|---|---|
| 字节数 | 1,344,964 | 1,346,517 |
| MD5 | `CD63A9C2…` | `FCFCE04F…` |
| 逐帧 PSNR | `inf` **99** 帧 / 非 inf **101** 帧,**最大 `mse_avg` = 0.53** |

⇒ **「同源双渲,解码像素不同」成立(101/200 帧),但幅度是 0.53 而非报告里的 0.082**
(口径不同:我用 mp4 单独双渲后 `psnr` 比对;`encoder-noise.py` 是 320×180 灰度
平均绝对差)。作者的**操作结论**(像素法不能证明「只改了该改的」)因此**更强地成立**。

### 我的判断(区分「已否证」与「未复现」)
- **已否证**:「渲染本身有可观测的非确定性」—— 在我的条件下(同一 checkout、同一机器、
  同一 `remotion` 版本、同一并发设置)**100+ 次全同**。
- **不能否证**:作者声称的那个变体可能在**别的条件**下出现(不同的 `--concurrency`、
  不同的 GPU/`--gl`、字体首次加载竞态、机器负载、或改文件后第一次渲染的缓存冷启动)。
  我**没有**穷尽这些条件,所以我不断言「渲染绝对确定」。
- **然而**:作者把一个**自己没复现、且我复现不出来**的数(`249px = 0.012%`、`8 次 still 得 5:1`)
  写进 `ACCEPTANCE.md` 的「确定性」节,并**作为既定事实**用来改写因果表述。
  这**恰好是它自己反复记录的那类错误的镜像**:用「别人报的数」当「实测」。
  按作者自己的方法论标准(「用来证明自己合规的证据,本身也要被审查」),
  这一节现在属于**引用他人未独立复现的证据**,应标注来源与复现条件,
  而不是与自己的实测数字并列。

---

## 文档过度声称 / 混口径 检查

| 位置 | 问题 | 判定 |
|---|---|---|
| `DELIVERY.md:151` 与 `ACCEPTANCE.md:278` | 写「成片复核已见 …**+00:00**」,与 `DELIVERY.md:214` 的「重渲后成片已见 `Z`」**矛盾**;成片实测是 `Z` | **文档错误(新发现)** |
| `DELIVERY.md:405` | 「必须覆盖 `apps/web` 传递依赖」—— 脚本实际 0 个 apps/web | **文档承诺 > 实现** |
| `DELIVERY.md:211`「82 个文件」vs `:225`「共 80 个文件」vs `ROUND_STATE.md:36`「80 个文件」 | 计数不一致(且这一节本身正在被并发编辑) | 编辑中,建议定稿后统一 |
| `DELIVERY.md:214` | 「影片 `+00:00`(Python `.isoformat()`)」—— 对 DB 的 `isoformat()` 而言成立;Pydantic 对 UTC 输出 `Z` 的说法也对。**口径标注清楚 ✅** | 可接受 |
| `ACCEPTANCE.md:358` | 「f2000/f4200/f5100 全部相同」—— **我实测三个哈希全部复现**(`460798D458AAE612` / `9AB90A76D98895E7` / `8E2A164CCDD064B2`),即**作者自己的抽样点确实稳定** | **✅ 实测一致** |
| `ACCEPTANCE.md:196-203` 空帧四口径 | 我跑 `blank-sensitivity.py`:②=147/112/101/90、③=14/5/2/1、①④=0/0/0/0 → **与声称一致**,「只引用①④」的结论**站得住** | **✅ 实测一致** |
| `DELIVERY.md:385` 边距「全片逐帧」 | 我跑 `bezel-scan.py`:扫描帧数 **5250**,最小 **11px (S6 f3559)**,各段 19/13/29/11/23/18 —— **与文档逐值一致** | **✅ 实测一致** |
| `DELIVERY.md:126`「`.btn:disabled{opacity:.5}`」 | 产品 `components.css:254` 确为 `opacity: 0.5`;影片 `EmergencyFormView.tsx:179` 用 `0.55`,且其注释写「产品里…是 0.5」。**数值有意微调、注释如实** | 可接受 |

**关于「混口径」(缩放 vs 全分辨率)**:
- 空帧节**明确标注了** 320×180 / 640×360 / 960×540 / 1920×1080 四档,并说明
  ②③ 不可跨尺度引用;**没有混口径 ✅**。
- 静止率节**明确标注**「口径 320×180,阈值 0.35」,并在 `motion-fresh.py:11-12`
  注明全分辨率会得 7.3% vs 9.1%;`ACCEPTANCE.md:249` 用的 8.9% 与**我现测的 8.9% 一致 ✅**。
- 唯一的口径含糊处在**确定性一节**:作者并列表述了「PNG 0.012% 单行」与
  「H.264 按 GOP 放大」,但**没有给出后者自己的量化**(我实测 mp4 最大 `mse_avg` 0.53)。
  「按 GOP 放大到整段的量级」目前是**推断**,不是实测 —— 我同意方向,但它被写得像实测。

---

## 我无法验证的

1. **前一位复核者的渲染条件**。我复现不出它的 `249px/0.012%` 变体,但也没能穷尽
   它的环境(并发度、`--gl`、缓存冷启动、GPU)。因此「渲染是确定的」这句我**不说**,
   只说「在我的条件下 100+ 次未复现」。
2. **`public/textures/**` 的消融**。作者声称已做过真消融(PNG 哈希不变)。我核实
   全仓**零引用**,与该结论一致,但**没有自己再做一次渲染级消融**(需要移走 73 个
   文件再渲染,收益低于成本)。
3. **`docs/design/tokens.css` 的影响链**。我确认它是 sync 真源、且不在清单内,
   但**没有实跑**「改真源 → sync → 重渲 → 画面变」的完整闭环(需要跑前端构建链路)。

---

## 一句话结论

**这 5 项修复不可接受为「已完成」:第 1 项(P0 清单覆盖)与第 4 项(source-delta)
的核心目标都未达成 —— 清单对 CSS 样式层仍完全失明(改 `--accent` 能改画面而两道门禁
全绿 + exit 0),`source-delta.py` 的文件宇宙仍 0 个 `apps/web` 且基线的名字前缀判据会
选中过期成片;第 2 项中 `bezel-scan.py` 仍保留一个「扫到帧但无段命中 ⇒ 9999px + exit 0」
的永不失败出口;第 3 项两处保真修正与第 5 项的 H.264 非位确定性成立,但第 5 项
「渲染非确定」我 100+ 次复现不出,文档把它当实测是新的过度声称。**

## 复现命令清单(均在仓库根)

```powershell
# ① P0:CSS 消融 → 门禁全绿(还原后 git diff 为空)
uv run python marketing/promo-shotcraft/.tmp/rev4/ablate.py backup apps/web/src/shared/styles/tokens.css
uv run python marketing/promo-shotcraft/.tmp/rev4/ablate.py patch  apps/web/src/shared/styles/tokens.css "--accent: #c2410c;" "--accent: #0c41c2;"
cd marketing/promo-shotcraft
pnpm exec remotion still src/index.ts Promo "<abs>/.tmp/rev4/ablA-f400.png" --frame=400
cd ../..
uv run python marketing/promo-shotcraft/verify/doc-consistency.py ; echo "exit=$LASTEXITCODE"   # → 0,且报「82 个文件一致」
uv run python marketing/promo-shotcraft/.tmp/rev4/ablate.py restore apps/web/src/shared/styles/tokens.css

# ① 阳性对照:清单内文件 → 门禁必须失败
uv run python marketing/promo-shotcraft/.tmp/rev4/ablate.py patch apps/web/src/features/library/domain/labels.ts "owner: '项目所有者核准'," "owner: 'XX-ABLATION-XX',"
uv run python marketing/promo-shotcraft/verify/doc-consistency.py ; echo "exit=$LASTEXITCODE"   # → 1
uv run python marketing/promo-shotcraft/.tmp/rev4/ablate.py restore apps/web/src/features/library/domain/labels.ts

# ① 差集
uv run python marketing/promo-shotcraft/.tmp/rev4/closure-audit.py

# ② bezel-scan 残留出口
uv run python marketing/promo-shotcraft/verify/bezel-scan.py marketing/promo-shotcraft/out/s1seg.mp4 ; echo "exit=$LASTEXITCODE"  # → 9999px / exit 0

# ③ 两处保真
uv run python marketing/promo-shotcraft/.tmp/rev4/db-case.py      # DB 真实值 + wire 格式
uv run python marketing/promo-shotcraft/.tmp/rev4/meta-parts.py   # itemMetaParts 6 段复算
ffmpeg -v error -y -i marketing/promo-shotcraft/out/promo-v16.mp4 -vf "select=eq(n\,4935)" -vsync 0 -frames:v 1 .tmp/rev4/film-4935.png

# ④ source-delta 宇宙与基线
uv run python marketing/promo-shotcraft/.tmp/rev4/delta-universe.py

# ⑤ 确定性
pwsh -File marketing/promo-shotcraft/.tmp/rev4/determinism.ps1      -Frame 1500 -N 16
pwsh -File marketing/promo-shotcraft/.tmp/rev4/determinism-seq.ps1  -Frame 997  -N 14
pwsh -Command "& 'marketing/promo-shotcraft/.tmp/rev4/determinism-sweep.ps1' -Frames 1497,1499,1500,1501,1503,1505 -N 8"
pwsh -File marketing/promo-shotcraft/.tmp/rev4/nondet-mp4.ps1        # 同源双渲 mp4:101/200 帧不同,max mse_avg 0.53
```
