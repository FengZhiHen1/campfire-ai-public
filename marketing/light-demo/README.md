# 腾讯 LIGHT 3 分钟演示视频工程

> 完整技术方案见 `.tmp/视频制作/Campfire-AI_腾讯LIGHT_3分钟演示视频技术方案.md`(动工时随本目录入库)。
> 已裁决事项:构图 A(设备框 + 侧信息区) · TTS 占位 → 真人终版 · 旁白预算 ≈600 字。

## 当前状态(占位粗剪)

- [x] 工程初始化,与主仓 pnpm workspace 隔离(workspace 只含 `apps/web`,天然隔离)
- [x] 全片时间线总装(175s,六段,`remotion/lib/timeline.ts` 为唯一真源,
      与 `screenplay/narration.md` 二稿段预算一一对应)
- [x] ①②⑥ Motion 段接近成品(品牌 logo 用 `docs/design/assets/brand-mark.svg` 内联)
- [x] ③④⑤ 占位 Capture:按 `docs/design/pages/` 页面设计稿做的风格化近似屏
      (`remotion/placeholders/`),镜头运动(zoom/Hold/快切)已是设计形态
- [ ] Playwright 真实录屏逐段替换占位屏(`OffthreadVideo`,deviceScaleFactor 3)
- [ ] edge-tts 草稿旁白 + 逐字时间戳(替换底部 caption 的时机由旁白对齐)
- [ ] Rough Cut → Motion Pass → 字幕 → 终稿

## 结构

```text
remotion/
  lib/timeline.ts     — 时间线唯一真源(改段长先改 screenplay,再同步此处)
  lib/tokens.ts       — docs/design/tokens.css 的镜像,不发明新值
  lib/brand.tsx       — brand-mark.svg 内联组件 + flame-dot 呼吸点
  components/         — PhoneFrame(构图 A 设备框,支持焦点 zoom)、InfoSide
  placeholders/       — 六张风格化占位屏(真实录屏到位后弃用)
  scenes/             — 六段场景,S1-S6 与脚本段落一一对应
```

## 命令

```bash
pnpm install          # 独立工程,不进主仓 workspace
pnpm dev              # Remotion Studio 预览
pnpm render:preview   # 渲染 preview.mp4
pnpm render:final     # 渲染终稿(CRF 18)
```

## 视觉契约

颜色与字体直接取自 `docs/design/tokens.css`:暖米纸 `#fbf6ee` / 火焰橙 `#c2410c` /
暖墨 `#201914` / 思源宋体标题栈。**不要在本工程里另设一套品牌色。**
