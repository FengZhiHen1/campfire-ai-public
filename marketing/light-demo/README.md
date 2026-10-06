# 腾讯 LIGHT 3 分钟演示视频工程

> 完整技术方案见 `.tmp/视频制作/Campfire-AI_腾讯LIGHT_3分钟演示视频技术方案.md`(动工时随本目录入库)。
> 已裁决事项:构图 A(设备框 + 侧信息区) · TTS 占位 → 真人终版 · 旁白预算 ≈600 字。

## 当前状态(骨架)

- [x] 工程初始化,与主仓 pnpm workspace 隔离(workspace 只含 `apps/web`,天然隔离)
- [x] 最小 Remotion 渲染链:Title Card + 构图 A 占位 → `output/preview.mp4`
- [ ] scenes.yaml 数据驱动时间线
- [ ] Playwright 场景录制(deviceScaleFactor 3)
- [ ] edge-tts 草稿旁白 + 逐字时间戳
- [ ] Rough Cut → Motion Pass → 字幕 → 终稿

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
