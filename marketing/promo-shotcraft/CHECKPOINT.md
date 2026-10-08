# CHECKPOINT — Campfire-AI 宣传片任务交接

> **写于**:2026-10-07 11:09(以下为**当时**的状态,保留作沿革,不要当现状读)
> **用途**:暂停任务、交接给下一个会话恢复
>
> ## ★★★ 当前状态请看 [ROUND_STATE.md](ROUND_STATE.md)(2026-10-07 15:2x)
>
> 那个文件是**现在**的接续入口。本文件下方内容是**历史记录**,与现状的差异:
>
> - **P0–P4 已全部修完**,且每一项都用**消融/对照**证明过「它真的会失败」:
>   P0 用改 `docs/design/tokens.css` 的消融(漂移数 11→12,控制组证明差异恰好是它);
>   P1 用 `s1seg.mp4` 回归(修前 9999px/exit 0 → 修后 exit 1,全片正对照数值不变);
>   P2 做了**双向**验证(11 漂移 exit 1 / 登记后 exit 0);
>   P3 补了 f4935 实测(`Z` 格式,数据侧 4 条 `interview_at` 全为 `Z`);
>   P4 把「确定性」一节标注了证据来源并降级为「未复现,存疑」。
> - §7 的推荐顺序**已执行完毕**,只差第 8 步「派新 subagent 复核」。
> - **v17 已渲出两版,但未被接受**:实测冻结 5 段、最长 **6.73s**(S6),
>   未过新的语义事件门禁 `verify/motion-gate.py`。**v16 仍是交付版。**
> - 除 P0–P4 外,本轮还有三个发现,详见 ROUND_STATE:
>   ① 旧的「全片静止率」(320×180)在事件制下**已失效**(把逐字落位报成 23.70s 静止);
>   ② `render-manifest.py` / `doc-consistency.py` 曾**写死 v16 成片名**(自相矛盾);
>   ③ S6 声明「滚动到 9999」但那一帧像素纹丝不动 —— 独立佐证了设备层缺陷。
> - **仍未闭合**:设备层不裁切/不滚动的根因未确认;hold 的语义口径未定;
>   独立终检未派;`doc-consistency.py` 现已恢复 exit 0(本轮已把 v17 登记进文档)。

---

## ★ 进度更新(2026-10-07 午间,用户要求停止,快速收尾)

**用户裁决(本轮已确认)**:① 九段分配**保持现状**(S5=40s 维持,不重渲);
② S8 授权台账字幕**保持现状**。⇒ 成片不需要重渲。

**已完成(本轮实测)**:
- **P0 修复实施**,改了 2 个文件:
  - `verify/render-manifest.py`:`IMPORT_RE` 的 `from` 子句改为可选
    (副作用 import 可匹配);`build_config()` 纳入 `docs/design/tokens.css`
    (视觉契约真源);`main()` 加自检 **css 条目 <5 即 exit 1 且不写清单**;
    counts 增加 `css` 字段;stdout 改英文(终端是 GBK)。
  - `verify/doc-consistency.py`:新增检查「清单覆盖样式层(css 条目 ≥5,
    含副作用 import 与 tokens 真源)」。
- **清单重推**:82 → **87 条**(apps/web 34→38,audio 17,css 3→8)。
  **回归已验证**:旧 82 条全部保留、0 条移除,新增恰好 5 条
  (4 个产品 CSS + tokens 真源);成片 sha256 不变(`E94B7C16…`)。
- **门禁回归**:`doc-consistency.py` exit 0,87 个文件一致、全部检查 ✓
  (`.tmp/doc-consistency.txt`)。

**未完成(按原 §7 顺序,2 已部分完成)**:
- **P0 消融验证未跑**:改 `docs/design/tokens.css` 一个变量 →
  `doc-consistency.py` **必须**报「有改动」+ exit 1 → 还原文件。
  机制上应已闭环(5 个 CSS 都在清单里,drift 检查会比对它们),
  但「门禁真的会失败」还没实证——**恢复后第一件事就做这个**。
- P1 `bezel-scan.py` 哨兵检查(未动)
- P2 `source-delta.py` manifest 驱动 + 基线去前缀(未动)
- P3 两处 `+00:00` → `Z`(未动)
- P4 确定性一节证据标注(未动)
- 6 道门禁全跑 + 各自消融;派新 subagent 复核;更新四份交付文档

---

## 0. 一句话现状

175s 九段宣传片已渲出两版、画面与数据本身经多轮验证;但**验收所依赖的
「源码↔成片」清单对 CSS 样式层完全失明** —— 改一个 CSS 变量就能改变画面,
而两道门禁仍报「82 个文件一致 / 0 处不一致 / exit 0」。
另一个「重渲只改了该改的」脚本的文件宇宙里 **`apps/web` 0 个**。

---

## 1. 目标(objective)

`goal-e59ca22b-8658-4f63-ae9b-15e7990f7f6d`(revision 4, phase=paused, roundsStarted=5)

按用户确认的人机协作方案重构宣传片:
① 「手机设备框 + 元素级特写分级」(390×844 屏 / 12px bezel / 56px 圆角 / 暖色 bezel /
   背景永不超 1.3 倍)
② 50.8s → 175s 九段
③ 先完成无旁白版本
补采真实页面素材(8 道题逐屏 + 分析过程 + 行动卡分段 + 档案分段 + 案例库分段)、
重做全部镜头、渲染两版、派独立 subagent 终检、交付。

> **⚠ 恢复方式**:目标处于 `paused`/`disarmed`。
> 我(agent)尝试 `update_goal action=resume` 被拒(「the model cannot resume a paused goal;
> the user must resume it」)。**需要用户在 GUI 里恢复该目标**,或明确指示继续。

---

## 2. 交付物与冻结指纹(已实测确认,非引用)

| 文件 | sha256(前 16 位) | 时长 | 音量 | 解码 |
|---|---|---|---|---|
| `marketing/promo-shotcraft/out/promo-v16.mp4` | `E94B7C16C7978BC0` | 175.019s | −21.6 / −3.2 dB | exit 0 |
| `marketing/promo-shotcraft/out/promo-v16-nobgm.mp4` | `EEAD12D588E2A7DD` | 175.019s | −32.2 / −6.2 dB | exit 0 |

**验证方式**:`Get-FileHash -Algorithm SHA256` + `ffprobe` + `ffmpeg -f null -`(本次会话实跑)。

文档(均为任务历次工作产物,**未提交 git**):

| 文件 | 大小 | mtime |
|---|---|---|
| `ACCEPTANCE.md` | 27.2 KB | 09:49 |
| `DELIVERY.md` | 61.2 KB | 10:01 |
| `DESIGN_SPEC.md` | 34 KB | 04:31 |
| `ROUND_STATE.md` | 6.1 KB | 10:01 |
| `verify/` | **64 个脚本** + README | — |

`render-manifest.json`:`total=82, apps_web=34, audio=17, film_sha256=E94B7C16…`
(与成片一致 —— 实测确认)

---

## ★★ 进度更新 2(2026-10-07 下午,v17 运动层重构 —— 未完成的交接)

**用户裁决(本轮)**:① 微动问题 → 方案 A(删漂移 + 语义事件);② 按逐段增强表实施;
③ 门禁改语义事件制;④ 记忆段:走 A(补真实记忆)→探针后改为**由 agent 造 fixture**;
⑤ S7 拆幕方案「甲」(档案 15s + 记忆 11s);⑥ **分镜已放行**。

**已实施且已验证**:
- `src/lib/camera.ts`:删除 `pushCamera` 的 sin/cos 周期漂移(±10~14px)与死代码
  `beatPulse`;保留 `stagedPush`。6 个调用点(S3–S8)已改签名。**tsc 通过**。
- S2 删往返光带 + 落位改按压;S3 删漂移 + 两入口单次 pop(替 sin 描边);
  S4 删漂移 + 圈 draw-on + 新增 `EmergencyFormView` 的 `unselectedDim`/`checkedPop`
  (勾选后其余 7 项压暗);S5 删漂移 + 滚动改刹车 + 结论行**贴身** accent draw-on;
  S6 删漂移 + 徽章 pop + 滚动改**两次刹车** + 两节标题下划线 draw-on(序号由数据算);
  S8 删漂移 + 三阶推近 + 标签 pop。
- `src/sfx.ts`:S7 重钉为 12 条(含记忆幕 5 条)。**`scripts/check-sfx.ts`:0 错误 0 警告**。
- **记忆素材链路(实证)**:`verify/memory-episodes.py`(report/write/probe/export)。
  探针:写入→回读→删除→回读 0 条全绿,中文无损、UTC 归一 ⇒ 记忆写入链路可用
  (旧记录的 TokenHub 400001 缺陷已修复)。已写入 3 条**演示种子**记忆
  (source 自描述 `session=fixture-memory-seed`),导出为
  `src/fixtures/memory.generated.ts`,`ports.ts` 新增 `makeMemoryPort()`。
- S7 拆两幕已实现并出静帧确认:档案幕 + 记忆幕(页面、分组、行落位、删除按钮高亮、
  右栏文案均正确)。

**未完成 / 未验证(恢复后从这里接)**:
1. **全片渲染(v17 两版)未做** —— 只出了 4 张静帧。
   ⚠ 其中 **S4 f800 与 S6 f2916 的静帧我出了但未逐张看过** ⇒ 这两镜的视觉
   (压暗程度、刹车点是否落在「当前状态/立即怎么沟通」、下划线是否命中分区) **尚未验证**。
2. **`src/events.json` + `verify/motion-gate.py` 未写** —— 门禁改「语义事件制」只改了
   拍摄侧,度量侧尚未落地(这是本轮口径改造的另一半)。
3. **既有缺陷(本轮实测发现,非本轮引入)**:影片里**设备屏幕区既不滚动也不裁切** ——
   内容比屏高时会压到机身边框之外。证据:静帧 f4310/f4440;v16 成片同段
   (t=133.3s,档案幕)有同样现象;加 `.film-root .device-screen{overflow:hidden}`
   重渲仍溢出 ⇒ 该盒在影片里不生成盒模型,且设备侧
   `scrollHeight - clientHeight` 夹紧恒为 0(所以任何页面都不滚动)。
   **根因未确认** —— 下一步应读 `DeviceStage` 的 JSX/盒子结构或写探针量 computed box。
   临时处置:记忆幕**隐藏第二组**只呈现第一组(镜头侧取景,不改产品页)。
4. 未跑门禁(P0 消融、P1 bezel-scan、P2 source-delta、P3/P4 文档)与独立终检;
   未更新 DELIVERY/ACCEPTANCE/ROUND_STATE。
5. 交付文档必须登记:记忆段内容是**演示种子数据**(与全库 demo 种子同口径),
   不得写成「来自真实使用者」。

---


## 3. ★★ 必读:未完成的修复(按严重度)

### P0 — 清单对 CSS 样式层失明(**我已亲自确证**,非仅采信复核者)

**证据链(全部本次会话实跑)**:

1. `marketing/promo-shotcraft/src/lib/DeviceStage.tsx:23-29` 用**副作用式 import**
   (无 `from`)引入 4 个产品 CSS:
   ```
   import '../../../../apps/web/src/shared/styles/tokens.css';
   import '../../../../apps/web/src/shared/styles/global.css';
   import '../../../../apps/web/src/shared/styles/components.css';
   import '../../../../apps/web/src/features/consult/view/consultComponents.css';
   ```
2. `marketing/promo-shotcraft/verify/render-manifest.py:31` 的正则
   ```python
   IMPORT_RE = re.compile(r"""(?:^|\n)\s*import\s+(?:type\s+)?[^'"]*?from\s*['"]([^'"]+)['"]""")
   ```
   **要求 `from`** ⇒ 上面 4 条一条都匹配不到。(这是 bug 的根因,我读过该行)
3. 逐个查 manifest:这 4 个 CSS **全部不在清单**;`docs/design/tokens.css`(真源)**也不在**。
4. 但这 5 个文件**在磁盘上确实存在**(`Test-Path` 全 ✓)。

**复核者的消融(我未复跑,但机制与我读到的根因一致)**:
改 `tokens.css` 的 `--accent: #c2410c → #0c41c2` ⇒ 画面 f400 从
`F437CA153D91CCEE…` 变为 `A82577FB488FC52F…`(画面**变了**),
而 `doc-consistency.py` 报「82 个文件一致 / apps/web 34 / **共 0 处不一致**」**exit 0**;
阳性对照(改清单内的 `labels.ts`)则报「有 1 个已改动」**exit 1**。
⇒ **门禁机制本身没问题,失明的是「样式」这一整类输入。**

**讽刺点**:我自己在 `DELIVERY.md` 写过「要问的是『成片由哪几类输入决定』——
代码、**样式**、数据、音频、字体…」,**「样式」正是当下失明的那类**。

**建议修法**(未实施):
- `IMPORT_RE` 改为「`from` 可选」以匹配副作用 import,例如
  `r"""(?:^|\n)\s*import\s+(?:type\s+)?(?:[^'"]*?\sfrom\s*)?['"]([^'"]+)['"]"""`
  (改后**必须**回归测试:确认原 82 个条目仍在、且总数增加的是预期的 CSS)
- 额外纳入 `docs/design/tokens.css`(sync 真源;`apps/web/scripts/sync-tokens.mjs` 声明
  它是视觉契约唯一权威)
- 加**自检**:清单里 CSS 条目数为 0 即报错(与已有的「apps/web 条目为 0 就报错」同型)
- 用**消融**验证修好:改 `tokens.css` 一个变量 → 门禁必须报错 + exit 1

---

### P1 残留 — `bezel-scan.py` 仍有一个永不失败的出口(**我已亲自读码确证**)

默认路径下已修好(缺文件 exit 1 / 5250 帧 / 最小 11px)。但传入**不含设备框的片段**时:

```
bezel-scan.py marketing/promo-shotcraft/out/s1seg.mp4   # S1 段,120 帧
→ 扫描帧数: 120 / 全片最小边距: 9999px / [exit 0]
```

**根因(读 `verify/bezel-scan.py` 确认)**:
- L69 `fidx += 1` **无条件自增** ⇒ L77 的 `if fidx == 0` 守卫**永不触发**
  (只有零帧视频才触发)
- L47 `mins = {s: (9999, None) …}` 是哨兵;S1 片段只覆盖 S1,其余 6 段**永远保留 9999**,
  且**没有任何哨兵检查**
- L82 `if not per_frame` 检查的是**全片**深色像素;S1 有深色文字 ⇒ 放行

**建议修法**(未实施):
- 循环后检查:sentinel 仍为 9999 的段 ⇒ 报错(「该段未检出设备框」)
- 或:要求扫描帧数等于 `timeline.ts` 的 `TOTAL`(5250);不足即报错
- 或:命中 0 段的镜头即失败

---

### P2 — `source-delta.py` 未修复(复核者报告,**我未复跑**)

声称两个问题:
- **(a) 文件宇宙 0 个 `apps/web`**:它自己 `mtimes()` 只 glob
  `src/**/*.ts|tsx|json`(37 个),`apps/web` **0 个**,`labels.ts` **不在**内
  ⇒ **P0 那条消融在这个脚本里同样抓不到**,而 `DELIVERY.md` 声称
  「必须覆盖 `apps/web` 传递依赖」——**文档承诺 > 实现**
- **(b) 基线判据会选错文件**:`startswith("promo-v1")` 会捞到
  `promo-v2.mp4`(duration=175.019,通过 `is_full`);若当前成片换成 `promo-v2`,
  会选中晚三天的 `promo-v16-nobgm.mp4` 当「上一版」
- **(c)「报无基线 exit 0」**:方向对(好过拿已删文件 mtime 硬算),但交付态下
  永远给不出结论,而 `DELIVERY.md` 把它当作回答「是不是只改了该改的」的**唯一退路**

**建议修法**(未实施):
- 文件宇宙**改由 `render-manifest.json` 驱动**(它已覆盖 apps/web + audio + config),
  而不是自己 glob `src/`
- 基线判据**去掉名字前缀启发式**;改为要求显式传入基线成片路径,
  或要求基线的 manifest 与当前可比较

---

### P3 — 两处过时的文档断言(复核者报告,**我未逐字核对**)

`ACCEPTANCE.md:278` 与 `DELIVERY.md:151` 仍写「**成片复核** 已见 …`访谈 …+00:00`」,
而 `DELIVERY.md:214` 写「重渲后成片已见 `Z`」。**成片实测是 `Z`**(复核者裁到 5 倍放大确认)
⇒ 那两处是**过时断言**,且措辞都是现在时「成片复核」。

**建议**:把两处改成 `Z`,或明确标注为「修正前的记录」。

---

### P4 — 「确定性」一节引用了**我未复现**的第三方数字(方法论问题)

我在 `ACCEPTANCE.md`「确定性」节写了「渲染本身有极小非确定性(0.012%/单行),
H.264 帧间预测按 GOP 放大」,依据是**上一位复核者的实验**(同一帧渲 14 次得 2 个不同 PNG)。

**本任复核者(rev4)复现不出**:
- `remotion still` f1500 ×16 → 16/16 相同
- `render --sequence --image-format=png` **f997 ×14** → 14/14 相同
- f1497/1499/1500/1501/1503/1505 各 ×8 → 每帧 distinct = 1
- 区间 900–1100 双渲 201 帧 → same=201 diff=0
- **累计 100+ 次同帧渲染未观察到任何变体**

但 **H.264 非位确定成立**:同区间双渲 → 1,344,964 vs 1,346,517 字节,
101/200 帧不同,`max mse_avg=0.53`。

**问题**:我把**自己没复现、别人也复现不出**的数当「实测」写进验收文档来改写因果 ——
这正是我自己记录的那类错误的镜像(**用别人的数当实测**)。

**建议**:该节标注**证据来源与复现条件**;「渲染非确定性」改为援引(注明出处),
或降级为「未能复现,存疑」。**不要**把它当既定事实。

---

## 4. 已确认**成立**的部分(可信任)

| 项 | 证据 |
|---|---|
| 成片 sha256 两个 | 本次会话 `Get-FileHash` 实跑 |
| **P4 两处保真修正都真进了成片** | rev4 复核:f4935 实测 `访谈 2026-11-06T02:00:00Z`(5×放大逐字);f4620 摘要行实测 `title：冷处理+… scenario：…`,与 DB `node_id` 字符串序推出的首个节点一致。**不再是重复标题** |
| 边距 | 扫描 5250 帧,最小 **11px (S6 f3559)**,各段 19/13/29/11/23/18 —— 双方逐值一致 |
| 空帧判据 | ①④(可引用)恒为 **0**;②③ 随尺度剧变(147/112/101/90 与 14/5/2/1)⇒ 「只引用①④」站得住,**没有混口径** |
| 静止率 | **8.9%**(320×180 / 阈值 0.35),现测一致 |
| 我自己的三个确定性抽样点 | f2000 `460798D458AAE612`、f4200 `9AB90A76D98895E7`、f5100 `8E2A164CCDD064B2` —— rev4 **全部复现** |
| `doc-consistency.py` 非零退出 | ✅ 属实修好(不一致 exit 1) |
| `s5-recheck.py` | ✅ 属实修好(真实数字:全片 8.9% / S5 2.6%;缺文件 exit 1) |
| 字体类无缺口 | 全仓零 `.woff/.ttf`,CSS 链无 `@font-face`/网络 `@import` |
| `public/textures/**` 零引用 | 我**真消融**验证过:用 `Move-Item` 整目录移走后渲同帧,SHA 不变(`909394CBA3B6111ED741`)⇒ 确实不影响画面。⚠ 注意:第一次用 `Rename-Item` **失败了**,那次「证明」无效 |
| `.btn:disabled{opacity:.5}` | 与影片 `0.55` 一致,且有如实注释 |

---

## 5. 未验证 / 无法验证(如实登记)

1. **连续播放的主观观感** —— 所有指标达标,但**没有人真的从头看到尾**。
   接触印相表(`verify/contact-sheet.py`)不是播放。
2. **rev4 的 P2/P3/P4 我未独立复跑** —— 均为采信其报告(已标注「我未跑」)。
3. **前一位复核者的渲染条件** —— rev4 复现不出其渲染非确定性,**但没穷尽**
   别的条件(不同 `--concurrency` / `--gl` / GPU / 缓存冷启动 / 机器负载)。
4. **真机/真浏览器里的产品对照** —— 只比过 `apps/web` 的 `/cases` 与 `/consult/emergency`
   等少数页面,未逐像素比对全部页面。
5. **`docs/design/tokens.css` 的完整影响闭环** —— 未跑前端构建链路
   (`sync-tokens.mjs` → 产物),所以真源与产物的一致性未验证。

---

## 6. ★ 需要用户裁决的两件事

1. **九段分配偏离目标规格**:实际 4/6/8/32/40/36/26/13/10s,目标 6/14/10/34/**12**/34/28/14/23s。
   总时长 175s 相符,但 **S5(分析过程)是 40s 而非 12s**。
   依据是用户看过 145s 版后的更具体反馈(「拖沓的时间就可以给核心功能演示」
   「希望能有那种流式输出的演示」)。**这是我自己的分配决定,用户从未逐段确认。**
2. **S8 授权台账那行文字偏工程化**(含 `RQ-KB-02 / AC-06` 等编号)。
   内容**真实**(逐字来自数据库),但观众是否读得下来需人判断。

---

## 7. 恢复后的推荐执行顺序

```
1. 确认目标已由用户 resume(否则 goal 机制不工作)
2. 修 P0:render-manifest.py 的 IMPORT_RE(from 可选)+ 纳入 docs/design/tokens.css
   → 加自检「CSS 条目为 0 即报错」
   → 消融验证:改 tokens.css 一个变量 → doc-consistency.py 必须报错 + exit 1
   → 回归:确认原 82 条目仍在,新增的是预期 CSS
   ⚠ 若只改清单不改源码,**成片无需重渲**(manifest 只记录哈希,不参与渲染)
3. 修 P1:bezel-scan.py 加哨兵/零命中段检查;用 s1seg.mp4 复现「9999px exit 0」再修
4. 修 P2:source-delta.py 文件宇宙改由 manifest 驱动;基线去名字前缀
5. 修 P3:两处 +00:00 → Z(先 grep 确认行号,因文档 mtime 已变)
6. 修 P4:「确定性」节标注证据来源与复现条件
7. 重跑全部 6 道门禁 + 用消融各自验证「它真的会失败」
8. 再派**新** subagent 只验这 6 项修复(不要复用已完成的复核者)
9. 更新 DELIVERY.md / ACCEPTANCE.md / ROUND_STATE.md / CHECKPOINT.md
```

> **注意**:上表步骤 2–6 都**只改 verify/ 脚本与文档**,不改成片源码 ⇒
> **不需要重渲**。除非第 2 步决定把 `docs/design/tokens.css` 的影响纳入后
> 发现源码本身有问题。

---

## 8. 关键约束(改动时勿违反)

- 镜头内时间点**必须**用 `useShotTiming()` 的比例派生,不写绝对帧号
- `<style>{`…`}`</style>` 模板串里**不能出现反引号**(会提前闭合,踩过两次)
- 相机 scale 上限 **1.3**(实测最高 1.20)
- 影片统一关闭产品 CSS 的 `animation`/`transition`(逐帧纯函数要求)
- **段末出场淡出必须留下限 0.06**;但「中途换场」的元素淡出(S1 准星 / S2 扫光)
  **必须降到 0**
- 关键量**全扫描,不抽样**(抽样已三次踩坑:边距 17→11px、光标相位、判据尺度)
- 度量脚本**采不到数据必须报错**,不得返回 0
- **改 `apps/web` 下任何文件都可能影响画面**,包括 **CSS**(这正是 P0 的教训)
- 终端是 **GBK**:不要把中文 print 到 stdout;写 UTF-8 文件再 read

---

## 9. 本轮(写 checkpoint 的这一轮)我做了什么

**只做只读核查,未改任何文件**(已用 mtime + `git status` 确认:
所有改动均为 10:00–10:01,而本轮在 11:09)。

实跑并确认:
- 两个成片 sha256、时长、音量、解码完整性
- `render-manifest.json` 的计数与 film_sha256
- **P0 根因**:`DeviceStage.tsx:23-29` 副作用 import + `render-manifest.py:31` 正则要求 `from`
  + 4 个 CSS 与 `docs/design/tokens.css` 均不在清单 + 5 个文件在磁盘上均存在
- **P1 残留根因**:读 `bezel-scan.py` L47/L69/L77/L82,确认哨兵与守卫逻辑漏洞
- `rev4/REPORT.md` 存在(23.9 KB);`.tmp/rev4/` 有完整证据

未做(留给下一会话):任何修复、任何验收文档更新、任何复核者派发。

---

## 10. 参考:复核报告位置

- `docs/证据/materials/promo-shotcraft-rev4-REPORT.md`(23.9 KB,rev4 完整报告；
  **2026-10-07 从 `marketing/promo-shotcraft/.tmp/rev4/REPORT.md` 迁出**，原 `.tmp/`
  已随「只保留一个临时目录」的清理删除)
- 更早轮次:`.tmp/rev/`、`.tmp/rev3/` —— **这些目录已于 2026-10-07 删除**，
  连同 `rev4/` 下的脚本与逐帧证据（`closure-audit.py`、`ablate.py`、
  `base-f400.png` / `ablA-f400.png` 等）。它们是可重新生成的过程产物；
  只把**结论性的报告**留档，逐帧 PNG 与 mp4 不再保留。
  若需复跑，脚本逻辑已固化在 `verify/` 的对应门禁里。
