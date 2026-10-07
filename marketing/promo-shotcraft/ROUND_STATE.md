# 本轮工作状态（供下一轮接续）

> 目标:`goal-e59ca22b-8658-4f63-ae9b-15e7990f7f6d`(175s 九段宣传片重构)
> 当前:**第 6 轮(独立复核对冻结版)抓出的问题已全部处理并重渲**;
> 成片已更新为 `E94B7C16…`。

## 交付物（已冻结）

| 文件 | 说明 |
|---|---|
| `out/promo-v16.mp4` | 主交付,175.019s,sha256 `E94B7C16C7978BC0DF7DB8906E5C6CD0CDAE24E57104608CA700A8F8E4107ED0` |
| `out/promo-v16-nobgm.mp4` | 无 BGM 版,sha256 `EEAD12D588E2A7DDC31ED967E53390C3E75FF3E3539D7D3E3A299D65B9BF4507` |
| `ACCEPTANCE.md` | 验收报告 |
| `DELIVERY.md` | 交付文档(修正表已到 36 条) |
| `DESIGN_SPEC.md` | 设计规格 |
| `verify/` | 60+ 验证脚本 + 索引 README |
| `render-manifest.json` | 成片对应的源码内容哈希(**从 import 闭包推导**,63 个文件) |

> ⚠ **`out/` 下已无「上一版」成片** —— `source-delta.py` 与三个接缝对比脚本
> 因此会报「无基线可比」并退出,这是**正确行为**(不编造结论)。
> 若要恢复这些检查,重渲前把当前成片另存一份即可。

## 本轮修的东西(第 6 轮复核 + 自查)

### 两个真缺陷(P4 保真)
1. **来源行时间戳格式**:真实页面 `访谈 …T00:50:00**Z**`(Pydantic),
   影片曾为 `+00:00`(Python `.isoformat()`)。已改导出器 → 成片已见 `Z`。
2. **案例卡摘要行只是重复标题**:真实页面显示首个**内容节点**
   (`title：… scenario：…`,后端 `_first_node_summary()`);
   `ports.ts` 曾硬写 `snippet: raw.title`。已按产品同一条规则取节点 → 成片已见真实摘要。

### 两个「举证缺陷」(比缺陷本身更值得记)
3. **`render-manifest.json` 对 `apps/web` 完全失明**(P0)。
   37 个条目全是 `src/`,而 `src/` 从 `apps/web` import 17 处。
   复核者消融证实:改产品 `labels.ts` 的可见文案 → **画面变了**,两道门禁**全绿**。
   → 改为从 **import 闭包**推导(63 个文件,`apps/web` 34 个),并加自检
   「apps/web 条目为 0 就报错」。
4. **两个永不失败的门禁**(P1):`bezel-scan.py` 默认指向已删文件、输出「最小边距
   9999px」exit 0;`s5-recheck.py` 还漏 `:file=-`、输出「S5 静止率 0.0%」exit 0。
   → 默认路径改真实文件、零帧报错、`doc-consistency.py` 补非零退出、
   `s5-recheck.py` 改薄封装(复用已验证脚本)。

### 我自己的论断被否证
5. **「渲染确定、只有 H.264 不确定」写反了因果**。复核者渲同一帧 14 次得到
   **两个不同 PNG**(0.012%、单行),`remotion still` 也会中招。
   我抽的 f500/f750/f975 恰好落在稳定变体上 —— **第三次「抽样撞上周期」**。
   → 已更正为「渲染有极小非确定性,H.264 帧间预测按 GOP 放大」。
   **操作结论不变且更强**:像素法(含无损 PNG)都不能证明「只改了该改的」,
   必须回到源码层。

### 判据稳定性
6. **空帧口径 ②③ 不可引用**:受控扫描证明它们随分析尺度剧变
   (②:146/112/101/90;③:14/5/2/1),而 ①④ 恒为 0。
   → 验收只引用 ①④。**新增教训:不仅要报口径,还要检验判据的稳定域。**

### 自查发现的同型缺陷
7. `seam-before-after.py` 在对照文件被删后,把「读不到」当成 0,
   输出「修前全为 0 → 修后 8/8」(真实 7/8)。→ 加前置检查;
   同类隐患一并修:`ab-diff.py` / `s5-why.py` / `seam-fix-evidence.py`。

## 未完成 / 待接续

1. **第 6 轮的修复本身还没有独立复核** —— 我改了 manifest 推导、两个门禁、
   两处保真缺陷。下一轮建议:**派新 subagent 只验这 5 项修复**
   (尤其 manifest 闭包是否真的覆盖所有会影响画面的文件,
   以及新成片 `E94B7C16` 里的两处 P4 修正)。
2. **两处需用户裁决**:
   - 九段分配偏离目标规格(S5 40s vs 目标 12s);依据是用户后一条更具体的反馈
   - S8 授权台账那行文字偏工程化(内容真实但冗长)
3. **f0–f9 属「近空白」**(只有准星线,非纸色像素 0.008%)。已登记为可调项。
4. **未实现的景别**:单元素满屏放大(截图路线的 L5)。已说明是有意取舍。
5. **N3 未判定**:S5 在 V1→V2 之间是否有真实变化 —— 复核者与我**都无法用像素法判定**,
   且现在已无基线。需源码层 diff 才能定论(目前按「无变化」处理,因为改动都有登记)。

## 复跑命令（仓库根）

```bash
cd marketing/promo-shotcraft
pnpm exec tsc --noEmit -p tsconfig.json          # → exit 0
npx tsx scripts/check-sfx.ts                     # 67 条,0 错 0 警
npx tsx scripts/check-classnames.ts
cd ../..
V=marketing/promo-shotcraft/verify
uv run python $V/render-manifest.py               # 重建清单(import 闭包)
uv run python $V/doc-consistency.py               # 指纹+内容哈希+静止率现测 → 不一致 exit 1
uv run python $V/audit-fixtures.py
uv run python $V/blank-verdict.py                 # 主判据:最大偏离≤1 → 0 帧
uv run python $V/bezel-scan.py                    # 全片逐帧,最小 11px
uv run python $V/motion-fresh.py marketing/promo-shotcraft/out/promo-v16.mp4
uv run python $V/contact-sheet.py                 # 通看全片(改完镜头务必看一眼)
```

## 关键约束（改动时勿违反）

- 镜头内时间点**必须**用 `useShotTiming()` 的比例派生,不写绝对帧号
- `<style>{`…`}`</style>` 模板串里**不能出现反引号**
- 相机 scale 上限 **1.3**(实测最高 1.20)
- 影片统一关闭产品 CSS 的 `animation`/`transition`
- **段末出场淡出必须留下限(0.06)**;但「中途换场」的元素淡出(S1 准星 / S2 扫光)
  **必须降到 0**
- 关键量**全扫描,不抽样**(抽样已三次踩坑)
- 度量脚本**采不到数据必须报错**,不得返回 0
- 改 `apps/web` 下任何文件都**可能**影响画面 —— 清单已覆盖 34 个产品文件
