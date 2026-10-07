# T07 审查裁决（编排器）—— P1 成立**且比审查者引的条款更硬（MUST）**；批准一次窄范围返工

对象：`verification/T07.md`（首行 `结论: FAIL`，P0=0 / **P1=1** / P2=3）。
**编排器独立复核**：读了源码、**自己抓了 ARIA 1.2 原文**、**实测了 jsdom 的 `inert` 支持**。

## 一、P1（`inert` 缺失）：**成立，且我查到的条款比审查者引的更硬**

**审查者的依据**：ARIA 1.2 里 AT 是 **MAY**、作者是 **SHOULD** mark all other contents as inert。

**我抓 ARIA 1.2 原文（`w3.org/TR/wai-aria-1.2/#aria-modal`）发现更硬的一条**：
> 「When a modal element is displayed, authors **MUST** ensure the interface can be controlled
> **using only descendants of the modal element**.」

**而这恰好是本实现失效的形态**：审查者实测——**焦点在背景时 Tab 逃出**（焦点陷阱挂在**单自身**的
keydown 上，事件到不了单）、**背景可聚焦**、**按真实 Enter 真的导航到 `/settings/memory`**。
⇒ **界面被「非后代」控制了** ⇒ **违反的是 MUST，不是 SHOULD**。

**我在源码侧确认**（这是判定的基础，不只是浏览器现象）：
- `ConfirmSheet.tsx` 里 **`inert` 命中数 = 0**（**完全没有实现**）；
- 全仓 `src` 里 `inert` 的 3 处命中**全在注释里**，且**内容正是「承认这是残余」**：
  `SettingsPage.tsx:160`、`ProfilePage.tsx:650` 写「已知残余（比原生模态少两项）：其它内容不做 `inert`」；
  `ConfirmSheet.test.tsx:60` 写「背景内容当作仍在 Tab 序里（**有意如此**…）」。
⇒ **项目自己已经记录了这个缺口**，但从「已登记的残余」变成了**实测可被利用的可达性缺陷**
（背景可被 Enter 真实激活 ⇒ **不只是「读屏能读到」，是「能被操作」**）。

**⇒ 级别：P1**（我维持，并有更强的依据）。理由：**不是「少一个锦上添花的属性」**，
而是**「模态语义被声称（`aria-modal="true"`）却未兑现」**——
本项目明令禁止「**未验证就声称**」，而这里更进一步：**声称了并且实测不成立**。

## 二、**我实测出修复的关键约束**（审查者没提，但决定修复能不能留测试）

**jsdom 30.1.1 对 `inert` 的支持**（我实跑）：
```
inertPropExists: false          ← 属性不反射
setInertTrue: true              ← 赋值能存下（但只是普通属性）
attrReflected: false            ← .inert=true 不产生属性
focusStillWorks: true           ← jsdom 不实现 inert 的聚焦抑制
```
**我进一步实测**：
```
bg.setAttribute('inert','')  ⇒ hasAttribute('inert') === true    ✓ 可观测
bg.removeAttribute('inert')  ⇒ hasAttribute('inert') === false   ✓ 可观测
```
⇒ **修复必须用 `setAttribute('inert','')` / `removeAttribute('inert')`，
不得用 `el.inert = true`** —— 否则 **jsdom 里的回归断言看不到任何变化**（`attrReflected: false`）。
**这条我要求写进代码注释**（下一个改这里的人会踩同一个坑）。

## 三、返工范围（窄：**只修 P1 + 顺手修 P2-1**）

### 必须做

1. **确认单打开时对「单之外的兄弟」施加 `inert`，关闭时恢复**
   - **结构约束**：`ConfirmSheet` **无 portal**（我确认它渲染在 React 树原位）
     ⇒ 需对**单祖先链之外的兄弟子树**施加 `inert`（**逐级向上**处理兄弟，或对
     「`document.body` 的子链上不属于本单的兄弟」处理）；
   - **⚠ 窄视口陷阱**：窄视口下 `.device` / `.device-screen` 是 **`display: contents`**
     （`global.css:118`）⇒ **不能用「盒几何」找兄弟**，必须按 **DOM 结构**遍历；
   - **必须用 `setAttribute`/`removeAttribute`**（见 §二），并把原因写进注释；
   - **必须恢复**：关闭后（含 Esc、遮罩点击、取消、确认）`inert` **全部移除**，
     且**不残留**（给出实测：关闭后 `document.querySelectorAll('[inert]').length === 0`）。
2. **补一条 jsdom 可断言的回归测试**：打开 ⇒ 背景兄弟带 `inert`；关闭 ⇒ 无 `inert`；
   **并保留** `ConfirmSheet.test.tsx:60` 附近那条「背景仍在 Tab 序里」的旧注释/断言的**语义更新**
   （它现在写「有意如此」——**修完后这句就过时了，必须改**，否则注释与代码矛盾）。
3. **同步那两处「已知残余」注释**：`SettingsPage.tsx:160`、`ProfilePage.tsx:650`
   现在写「其它内容不做 `inert`」⇒ **改完后这句必须改为已做**，并**保留仍存在的另一项残余**
   （「层级靠 z-index 而非 top layer」——那一项**仍未解决**，不要一起删掉）。
4. **P2-1 顺手修**：`T07` 报告与我的裁决书写的 `ProfilePage.tsx:49` / `MemoryPage.tsx:34`
   **行号漂移**，实为 **`:50` / `:35`**（我独立复核确认）。
   ⇒ **改报告里的行号**（不是改代码）。

### P2 我不要求返工的两条（登记即可）

- **P2-2（我的任务包 ① 判据在 ≥560px 空转）**：审查者指出 `.device { overflow: hidden }`
  （`global.css:152`）会**裁掉**溢出 ⇒ **文档级 `scrollWidth` 恒为 0**，
  于是**判据在 ≥560px 下量不出问题**。**审查者是对的，这是我的判据缺陷**
  ⇒ 它给了**元素级替代判据**（页头级溢出），并在改后产物上通过。
  ⇒ **登记为编排器失误**（判据的观测对象被祖先裁切）——**与 `§8b(n)`「判据选错现象」同族**。
- **P2-3（执行者红/绿跑的不是终局 bundle）**：审查者**在终局产物上自己重算了**
  （hits=3 RED / hits=4 GREEN）⇒ **结论无需返工**，但**登记**：
  **「证明某个断言会红/绿，必须在最终交付物上跑」**。

## 四、放行返工

**范围**：`ConfirmSheet.tsx`（+`inert` 逻辑）、`ConfirmSheet.test.tsx`（+回归、改过时注释）、
`SettingsPage.tsx` 与 `ProfilePage.tsx` 的**注释**（两处「已知残余」）、`T07.md` 的行号。

**验收判据**：
- [ ] **背景不可被操作**：打开确认单后，对背景元素**真实 Enter 不产生导航**（给实测：
      导航前后 URL 相同）；背景元素**不可聚焦**。
- [ ] **AX 树**：打开后背景节点数 **显著下降**（审查者实测：现状 84 → 注入后 0/28 节点）；
      给出你实测的两个数字。
- [ ] **关闭后无残留**：`document.querySelectorAll('[inert]').length === 0`（含 Esc/遮罩/取消/确认 四条路径）。
- [ ] **jsdom 回归断言**：打开 ⇒ 背景兄弟带 `inert`；关闭 ⇒ 无。
- [ ] **`setAttribute` 而非 `.inert =`**（并在注释里写明为什么）。
- [ ] **两处「已知残余」注释已更新**（改为「已做 `inert`」，**保留**「层级非 top layer」那一项）。
- [ ] **窄视口仍通过**（`display: contents` 下 `inert` 施加对象正确）——给 390 与 1280 两个视口的实测。
- [ ] **五门全绿**，vitest **≥426**（只增不减）。
- [ ] **不回归**：② 的四项（焦点进入/Tab 不逃出/Esc 归还/遮罩）+ ① 折叠 + ③ 标点**全部仍通过**。
- [ ] **产物可重建**（build 两次 sha 相同）。

**回归要求（重要）**：**② 的四项必须重跑**——因为 `inert` 会改变焦点行为
（例如把背景置 `inert` 后，**焦点陷阱的实现可能变得多余或行为变化**）。
**若 `inert` 让某项不再需要，不要擅自删除**——**报出来我再裁**。

## 五、编排器失误登记（进 `facts.md`）

**我的 ① 判据在 ≥560px 空转**：我要求量「**文档级** `scrollWidth`」，
但 `.device { overflow: hidden }` 会**裁掉**溢出 ⇒ **该读数恒为 0，量不出问题**。
⇒ **纪律（补强 `§8b(n)`）**：**选判据时必须问「这个读数会不会被我自己的布局裁掉/吸收？」**
——**祖先的 `overflow`、`display:contents`、`transform` 包含块都可能让判据失效**。
**审查者给的替代判据（元素级/页头级溢出）才是有效的观测对象。**
