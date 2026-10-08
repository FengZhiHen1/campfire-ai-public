# Campfire-AI 腾讯 LIGHT 3 分钟演示视频技术方案

> 目标：为 Campfire-AI 制作一套由本地 Agent 主导、可重复执行、可快速迭代的软件宣传视频生产流程。  
> 首期产物：腾讯 LIGHT 评委演示用 3 分钟 16:9 视频。  
> 核心原则：真实产品界面优先、代码化剪辑优先、本地 Agent 全流程接管、旁白来源可替换。

---

## 1. 方案目标

本方案不以“做一条视频”为终点，而是建立一套可以重复运行的 Campfire-AI 产品视频生产系统。

需要满足以下要求：

1. 视频主体必须来自真实 Campfire-AI 产品，不依赖生成式视频模型重构 UI。
2. 剪辑工作尽量由本地 Agent 完成，不依赖 CapCut、Premiere、After Effects 等 GUI 剪辑工具。
3. 本地 Agent 可以控制：
   - 产品录制；
   - 素材整理；
   - 视频剪辑；
   - UI 放大与聚焦；
   - 转场；
   - 标题与字幕；
   - Motion Graphics；
   - 音频处理；
   - 最终渲染。
4. 旁白支持两种来源：
   - TTS；
   - 人工配音。
5. 两种旁白必须可以无缝替换，不影响整体工程结构。
6. 第一阶段面向腾讯 LIGHT 评委演示，后续应能复用于：
   - Campfire-AI 官网宣传片；
   - 功能更新视频；
   - 30～60 秒 Promo；
   - 16:9 / 9:16 / 1:1 多尺寸输出；
   - 社交媒体内容；
   - 产品发布视频。

---

# 2. 核心技术路线

推荐技术栈：

```text
                    Local Agent
                         │
          ┌──────────────┼──────────────┐
          │              │              │
          ▼              ▼              ▼
      Playwright      Remotion        FFmpeg
      产品捕获        视频工程        媒体处理
          │              │              │
          │        ┌─────┼─────┐        │
          │        │     │     │        │
          │       剪辑   动画  字幕      │
          │        │     │     │        │
          └───────►│     │     │◄───────┘
                   │     │     │
                   └─────┼─────┘
                         │
                    Narration
                  ↙           ↘
                TTS          Human
                         │
                         ▼
                   Final Render
                         │
                         ▼
                campfire-light.mp4
```

核心组件：

| 组件 | 职责 | 优先级 |
|---|---|---|
| Local Agent | 总控、编排、修改、渲染 | 必须 |
| Remotion | 时间线、剪辑、动效、字幕、转场 | 必须 |
| FFmpeg | 转码、裁切、音频、编码 | 必须 |
| Playwright | 自动操作和录制 Campfire-AI | 强烈推荐 |
| TTS | 草稿旁白或最终旁白 | 可选 |
| 人工配音 | 最终真人旁白 | 可选 |
| CANVID | 特殊场景手工补录 | 可选 |
| CapCut / Premiere | 最终人工修补 | 非主链路 |
| AE / Jitter | 高级 Motion Design | 非必要 |

---

# 3. 技术选型说明

## 3.1 Remotion：作为核心视频工程

Remotion 不只用于“做动画”，而直接作为代码化视频编辑器。

本方案中，Remotion 负责：

- 时间线；
- 视频素材切片；
- 视频拼接；
- 镜头节奏；
- Zoom；
- Pan；
- Spotlight；
- UI Highlight；
- Caption；
- Title Card；
- Motion Graphics；
- Transition；
- Logo Animation；
- Voice Track；
- Background Music；
- Sound Effect；
- 最终 Composition。

核心思路：

```text
Traditional NLE

Premiere
  ↓
Timeline
  ↓
Keyframe
  ↓
Manual edit
```

改为：

```text
Local Agent
  ↓
Remotion Code
  ↓
Composition
  ↓
Render
```

例如：

```tsx
<Sequence from={0} durationInFrames={240}>
  <Intro />
</Sequence>

<Sequence from={240} durationInFrames={450}>
  <ProductDemo src="demo-01.mp4" />
</Sequence>

<Sequence from={690} durationInFrames={180}>
  <FeatureTransition />
</Sequence>
```

本地 Agent 可以直接修改：

- 起止帧；
- 速度；
- Zoom；
- 字幕；
- 转场；
- 动画；
- 音频；
- 画面层级。

---

# 4. Playwright：产品演示录制层

Playwright 用于自动控制 Campfire-AI Web 界面。

建议将演示过程拆成独立场景：

```text
scene-01
首页 / 产品进入

scene-02
输入任务

scene-03
Agent 开始执行

scene-04
Tool / Skill / Workflow 状态

scene-05
最终结果

scene-06
补充功能演示
```

每个场景独立录制。

不要尝试一次录完 3 分钟。

---

## 4.1 Playwright 的价值

相比手动录屏，它能提供：

- 固定分辨率；
- 固定浏览器尺寸；
- 固定鼠标路径；
- 固定点击流程；
- 固定输入；
- 固定滚动位置；
- 可重复执行；
- UI 更新后重新录制；
- 避免操作失误；
- 方便自动化。

推荐流程：

```text
Local Agent
    ↓
启动 Campfire-AI
    ↓
载入 Demo Account
    ↓
运行 scene 脚本
    ↓
自动录制
    ↓
生成 WebM / MP4
    ↓
交给 Remotion
```

---

# 5. FFmpeg：底层媒体处理

FFmpeg 不承担主要剪辑逻辑，而作为 Remotion 下层的媒体工具。

主要用途：

```text
视频转码
视频裁切
改变播放速度
音频标准化
音频抽取
音频合并
格式统一
MP4 / WebM 转换
H.264 编码
文件压缩
响度处理
```

典型任务：

```text
Playwright WebM
        ↓
FFmpeg
        ↓
标准化 MP4
        ↓
Remotion
```

---

# 6. 旁白方案

旁白层必须与视频工程解耦。

统一输入：

```text
assets/audio/narration.wav
```

Remotion 只依赖 `narration.wav`。

它不关心音频来自：

```text
TTS
```

还是：

```text
人工录音
```

---

## 6.1 推荐策略

推荐使用：

> TTS 做开发阶段占位，真人旁白做最终版本。

流程：

```text
旁白文稿
   ↓
TTS
   ↓
draft-narration.wav
   ↓
Agent 根据音频长度剪片
   ↓
视频结构稳定
   ↓
真人录音
   ↓
final-narration.wav
   ↓
替换 TTS
   ↓
Agent 自动重新对齐
```

优势：

- 不需要等待真人录音后再开始剪辑；
- 提前确定场景长度；
- 快速发现旁白过长问题；
- 便于 Agent 自动编排时间轴；
- 最终仍然保留真人表达。

---

# 7. 人工旁白处理

如果最终使用真人旁白，可由本地 Agent 调用 FFmpeg 做基础后期。

输入：

```text
voice-raw.wav
```

处理流程：

```text
High Pass
   ↓
Noise Reduction
   ↓
EQ
   ↓
Compression
   ↓
Loudness Normalization
   ↓
Limiter
   ↓
narration.wav
```

目标不是“录音棚级制作”，而是：

- 音量稳定；
- 人声清晰；
- 避免底噪；
- 避免爆音；
- 不同录制片段响度一致。

---

# 8. 建议目录结构

建议在 Campfire-AI 仓库中建立独立营销视频目录：

```text
Campfire-AI/
│
├── apps/
├── packages/
├── ...
│
└── marketing/
    └── light-demo/
        │
        ├── README.md
        ├── package.json
        │
        ├── screenplay/
        │   ├── narration.md
        │   ├── scenes.yaml
        │   └── shot-list.md
        │
        ├── capture/
        │   ├── playwright.config.ts
        │   ├── scene-01.ts
        │   ├── scene-02.ts
        │   ├── scene-03.ts
        │   ├── scene-04.ts
        │   └── scene-05.ts
        │
        ├── assets/
        │   ├── capture/
        │   ├── logo/
        │   ├── images/
        │   ├── audio/
        │   │   ├── narration.wav
        │   │   ├── music.mp3
        │   │   └── sfx/
        │   └── fonts/
        │
        ├── remotion/
        │   ├── Root.tsx
        │   ├── Main.tsx
        │   │
        │   ├── scenes/
        │   │   ├── Intro.tsx
        │   │   ├── Overview.tsx
        │   │   ├── Demo01.tsx
        │   │   ├── Demo02.tsx
        │   │   ├── Architecture.tsx
        │   │   └── Ending.tsx
        │   │
        │   ├── components/
        │   │   ├── Camera.tsx
        │   │   ├── Cursor.tsx
        │   │   ├── Caption.tsx
        │   │   ├── Spotlight.tsx
        │   │   └── FeatureCard.tsx
        │   │
        │   ├── transitions/
        │   ├── captions/
        │   └── utils/
        │
        ├── scripts/
        │   ├── capture.ps1
        │   ├── process-audio.ps1
        │   ├── render-preview.ps1
        │   └── render-final.ps1
        │
        └── output/
            ├── preview.mp4
            └── campfire-light-final.mp4
```

---

# 9. Scenes 配置

建议场景不要只写在 React 代码中。

增加：

```text
screenplay/scenes.yaml
```

例如：

```yaml
video:
  width: 1920
  height: 1080
  fps: 30
  max_duration: 180

scenes:

  - id: intro
    narration: intro
    type: motion
    target_duration: 8

  - id: demo-input
    narration: demo-input
    type: capture
    source: assets/capture/demo-input.mp4

  - id: agent-execution
    narration: agent-execution
    type: capture
    source: assets/capture/agent-execution.mp4

  - id: result
    narration: result
    type: capture
    source: assets/capture/result.mp4
```

这样 Agent 可以自动：

```text
读 scenes.yaml
      ↓
读 narration
      ↓
读取素材时长
      ↓
规划 timeline
      ↓
生成 / 修改 Remotion
```

---

# 10. 本地 Agent 的职责

本地 Agent 不是只负责“写代码”，而是视频生产线的总控。

Agent 需要具备以下职责：

## 10.1 项目理解

读取：

- Campfire-AI 源码；
- README；
- UI 组件；
- Logo；
- Design Tokens；
- 品牌色；
- 字体；
- 实际功能。

禁止：

- 虚构产品功能；
- 重画不存在的 UI；
- 修改产品实际行为；
- 使用假结果冒充真实能力。

---

## 10.2 录制控制

Agent：

```text
启动 App
   ↓
检查 Demo 环境
   ↓
运行 Playwright
   ↓
检查录制
   ↓
输出 Capture
```

---

## 10.3 自动剪辑

Agent 能处理：

```text
Trim
Speed
Crop
Zoom
Pan
Hold
Cut
Fade
Transition
Overlay
Callout
Highlight
Caption
```

用户可以直接给自然语言指令：

> 第二段前面删掉 1.2 秒。

> Agent 开始执行的时候把镜头 Zoom 到右侧状态栏。

> 模型等待过程保留 2 秒，然后跳到结果。

> 说到“工具调用”时高亮 Tool Panel。

> Result 出现之后停留 5 秒。

---

# 11. Agent Skill 设计

建议建立一个专用 Skill：

```text
campfire-video
```

---

## 11.1 Skill 应包含

### Brand

```text
Campfire Logo
Brand Color
Typography
Spacing
Background
Border Radius
Shadow
```

### Motion

定义统一的：

```text
Easing
Spring
Transition
Camera Movement
Zoom Speed
Cursor Style
Highlight Style
```

### Video

```text
1920 × 1080
30 FPS
16:9
≤ 180 sec
H.264
```

### Capture

```text
固定浏览器尺寸
隐藏无关 UI
关闭通知
固定 Demo Account
固定测试数据
统一页面 Zoom
```

### Content

```text
不得虚构 UI
不得虚构功能
不得展示未实现能力
真实产品优先
```

---

# 12. 视觉策略

本次腾讯 LIGHT 视频不建议做成 180 秒全动画。

推荐：

```text
约 65%～75%
真实 Campfire-AI 产品录像

约 10%～20%
Remotion Motion Graphics

约 10%
字幕 / Title / Transition

约 5%
Opening / Ending
```

---

# 13. 产品画面处理原则

软件 Demo 最重要的不是复杂动画，而是：

```text
看得清
看得懂
节奏快
重点明确
```

所以镜头主要使用：

### Zoom

```text
1.0
 ↓
1.10～1.20
```

一般不要过度放大。

### Focus

降低其他区域视觉权重：

```text
opacity
blur
dim
```

突出：

```text
Input
Tool Call
Agent State
Result
```

### Hold

结果页面必须停留。

不要：

```text
Result
 ↓
0.5 秒
 ↓
Cut
```

而应：

```text
Result
 ↓
Camera Hold
 ↓
Narration
 ↓
局部 Zoom
 ↓
Cut
```

---

# 14. Cursor 策略

宣传片不一定必须保留真实系统鼠标。

可选：

```text
Playwright 真实点击
        ↓
Remotion Synthetic Cursor
```

好处：

- 平滑；
- 统一；
- 更容易控制速度；
- 可以放大点击动画；
- 避免真实鼠标抖动。

---

# 15. 字幕

字幕应根据最终旁白生成。

流程：

```text
final narration
    ↓
ASR / timestamp
    ↓
caption JSON
    ↓
Remotion
```

字幕应：

- 每屏少量文字；
- 不遮挡产品核心区域；
- 字号足够大；
- 跟随旁白；
- 可人工校正。

---

# 16. 音乐与音效

音乐不应成为主要内容。

推荐：

```text
Narration
   ↓
Primary

UI SFX
   ↓
Secondary

Background Music
   ↓
Ambient
```

音效主要用于：

```text
Click
Transition
Result
Card Reveal
Logo
```

不建议大量加入“科技感”音效。

---

# 17. 首期腾讯 LIGHT 生产流程

推荐执行顺序：

## Phase 1：工程初始化

```text
建立 marketing/light-demo
       ↓
安装 Remotion
       ↓
安装 Playwright
       ↓
确认 FFmpeg
       ↓
建立 video skill
```

---

## Phase 2：准备 Demo 环境

建立：

```text
固定 Demo Account
固定数据
固定 Prompt
固定应用状态
```

确保录制时不会遇到：

```text
随机 Popup
随机测试数据
通知
登录过期
内容变化
```

---

## Phase 3：建立旁白草稿

```text
narration.md
    ↓
TTS
    ↓
draft-narration.wav
```

获得完整时间基准。

---

## Phase 4：拆分场景

形成：

```text
scenes.yaml
shot-list.md
```

每段产品 Demo 独立。

---

## Phase 5：Agent 自动录制

```text
Playwright
   ↓
scene-01
scene-02
scene-03
...
```

输出到：

```text
assets/capture/
```

---

## Phase 6：Agent 建立 Rough Cut

Agent：

```text
读取 narration
读取 capture
读取 scenes
     ↓
生成 Remotion Main
     ↓
生成 preview
```

第一版只解决：

```text
信息完整
节奏正确
时长正确
```

不急于做复杂动画。

---

## Phase 7：Motion Pass

增加：

```text
Camera
Zoom
Spotlight
Feature Title
Transition
Logo
Architecture Animation
```

---

## Phase 8：旁白最终化

二选一：

```text
TTS Final
```

或：

```text
Human Recording
```

统一为：

```text
narration.wav
```

---

## Phase 9：字幕与音频

```text
Final Narration
      ↓
Caption
      ↓
Music
      ↓
SFX
```

---

## Phase 10：最终渲染

推荐：

```text
1920 × 1080
30 FPS
H.264
AAC
16:9
```

输出：

```text
output/campfire-light-final.mp4
```

---

# 18. MVP 范围

第一版不要实现：

- 复杂 3D；
- 大量粒子；
- 大规模 Shader；
- AI 生成 UI；
- 自动 B-roll 搜索；
- 全自动生成 Storyboard；
- 多平台发布系统。

第一版只做：

```text
Playwright Capture
+
Remotion Edit
+
FFmpeg
+
Narration
+
Subtitle
+
Final Render
```

这是最高优先级。

---

# 19. 后续可扩展方向

当本次比赛视频完成后，可以继续扩展为：

## 自动 Feature Demo

```text
/product-demo feature-x
```

Agent：

```text
理解 Feature
   ↓
录制
   ↓
剪辑
   ↓
生成 30 sec Promo
```

---

## 自动多尺寸

同一 Composition：

```text
1920×1080
1080×1920
1080×1080
```

---

## 自动版本更新

Campfire UI 更新：

```text
重新运行 Playwright
       ↓
更新 capture
       ↓
重新 render
```

---

## CI 渲染

进一步可以：

```text
Git Commit
    ↓
CI
    ↓
Render
    ↓
Artifact
```

---

# 20. 最终推荐

对于 Campfire-AI 当前的腾讯 LIGHT 3 分钟评委演示视频，建议正式采用：

```text
Local Agent
    +
Playwright
    +
Remotion
    +
FFmpeg
    +
TTS / Human Voice
```

其中：

```text
Local Agent
= 导演 + 剪辑师 + Motion Engineer

Playwright
= 摄像机

Remotion
= Premiere + 部分 After Effects

FFmpeg
= 媒体处理基础设施

TTS / Human Voice
= 可替换旁白层
```

整个系统的核心价值不是单纯“AI 帮你做视频”，而是：

> 将软件宣传视频从一次性的手工剪辑，变成可由本地 Agent 持续维护和重新渲染的代码工程。

对于 Campfire-AI 这种仍在持续迭代的软件产品，这种方式比传统 GUI 视频制作更适合长期使用。
