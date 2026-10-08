# DSH 会话存活检测指南

> 针对单一目标：**`/dev-orchestrator 落地一期应用前后端开发`**
> 会话 id：`session-e9beef6d-7bd8-4d35-8e18-8bc9b2336e0d`
> 建立时间：2026-09-30，工作目录 `E:\Project\Web_Development\Campfire-AI`

## 1. 数据源在哪

DSH 把每个会话写成**追加写的多帧 zstd** 文件：

```text
%APPDATA%\in.dsh-plug.dsh-launcher\homes\stable-dev\sessions\
  --E-Project-Web_Development-Campfire-AI--\
    <session-id>\session.v4.jsonl.zstd
```

注意两点（都踩过坑）：

- **不是单帧 zstd**。`zlib.zstdDecompressSync(整个文件)` 只解出第一帧，会误以为文件只有一条 `session` 记录。必须**按帧魔数切分解码**：魔数是**大端 `28 B5 2F FD`**（我第一次按小端 `FD 2F B5 28` 扫，扫出 0 帧）。
- 解码用 **Node ≥23 内置的 `zlib.zstdDecompressSync`** 即可，不需要 zstd 命令行或第三方包。DSH 的 pnpm 存储里**没有**独立的 zstd 包。

事件形如（每行一个 JSON）：

```json
{"type":"turn/end","seq":1334,"time":1790781253662,"data":{"turn":13,"reason":{"kind":"completed"}}}
```

关键字段：`type`、`seq`（会话内严格递增）、`time`（毫秒）、`data.turn`、`data.step`。

## 2. 用到的事件类型

| 事件 | 用途 |
|---|---|
| `turn/start` / `turn/end` | 一轮的边界。`turn/end.data.reason.kind` 是**显式停止原因** |
| `step/start` / `step/end` | 步的边界，用于判断是否卡在半步 |
| `tool/call` / `tool/result` | 工具调用，按 `callId` 配对；未配对 = 工具还在跑 |
| `subagent/catalog` | **子代理派发登记**，含 `childId` 与 `label`（泳道名） |
| `agent/inbox/spliced` | 子代理回报被插入父会话上下文 |
| `compaction/*` | 上下文压缩，期间长时间静默属正常 |

## 3. 三条判定规则

**① 确定已终止** —— 读到 `turn/end`，看 `reason.kind`：

| kind | 含义 | 是否告警 |
|---|---|---|
| `completed` | 正常结束 | 否 |
| `aborted` (`reason.kind=user`) | 用户手动停 | 是 |
| `aborted` (`reason.kind=parent`) | 被父代理撤销 | 是 |
| `max-tokens` | 撞上下文上限 | 是（若无人接手） |
| `error` (`code=SERVER`) | 模型网关 503 `no_healthy_account` | 是 |
| `error` (`code=TRANSPORT`) | `Connection error.` | 是 |
| `interrupted` | 中断 | 是 |

（上表分布是本仓库 126 个会话上实测统计到的全部取值。）

**② 确定在跑** —— 连续两次采样 `seq` 有推进。**必须靠 seq 差分，不能靠文件时间戳**：文件被 touch 但内容没动是可能的。

**③ 疑似卡死** —— 无 `turn/end`，且连续 N 次采样 `seq` 不变、尾部停在未配对的 `step/start` 或 `tool/call`。

> ⚠️ **这一档是推断，不是事实。** 等模型生成和真死在磁盘上长得一样。实测反例：`f4ddc9b1` 曾连续 45 秒 seq 不动，按心跳阈值会被判死，实际是 15:19:11 发出 step/90 后在等模型，15:20:02 出推理后继续跑到 step 91。`compaction` 期间同样会长时间静默。所以默认 `stall=4`（约 2 分钟）才报，且标 `STALLED?` 带问号。

## 4. 编排器为什么长时间「不写消息」

这个目标会话**是编排器，本身不产出可见消息**。它的活动体现为：

- `subagent/catalog` 派发子代理（本目标已派 19 个，T01–T10 各泳道的执行/审查/重派）
- `agent/inbox/spliced` 接收子代理回报

所以：

- **编排器静默 ≠ 编排器死了。** 它可能已写完 `turn/end completed`，正在等子代理回调——脚本此时显示 `WAITING(n子)`。
- 判断它是否活着，要看它的**子代理是否在跑**，而不是它自己有没有新消息。

## 5. 用法

```bash
cd .tmp\session-watch
node watch.cjs --once                  # 采一次
node watch.cjs --watch                 # 默认 30s 轮询
node watch.cjs --watch --interval 15   # 自定义间隔
node watch.cjs --watch --stall 6       # 更保守的卡死阈值
node watch.cjs --watch --log           # 追加写 watch.log
```

退出码：`0` 正常，`2` 出现告警。

输出里各列：状态 / `seq` / `Δ`（本轮增量）/ 位置（`t<turn>/s<step>`）/ 静默秒数。

状态含义：

| 状态 | 含义 |
|---|---|
| `RUNNING` | 本轮 seq 有推进（首轮弱判定显示为 `RUNNING*`） |
| `QUIET` | 本轮无推进，但未达卡死阈值 |
| `STALLED?` | 连续 `--stall` 次无推进，**疑似**卡死 |
| `STOPPED(kind)` | 已终止，kind 见 §3① |
| `WAITING(n子)` | 编排器已 completed，仍有 n 个子代理在跑 |
| `INIT` | 首轮且未拿到可判数据 |

## 6. 已验证 / 未验证

**已验证（2026-09-30 实测）**

- 多帧 zstd 按大端魔数解码，746 帧全部解出（`0a7eecdd`）
- 目标会话的子代理树自动发现（不写死 id，中途新派的 `6a34ef5c`「T06 会话归属审查」被自动纳入）
- 两轮采样 seq 差分判定：`1a6bd333` 1111→1131、`0a7eecdd` 1571→1628、`da89ef64` 885→916、`f4ddc9b1` 547→557 均推进
- 告警抑制：`6e715991` 的 `max-tokens` 已被同泳道 `c582b4b4`「T10 前端账户页重派」接手完成，不再刷告警

**未验证 / 已知局限**

- **没查进程表**。若 DSH 进程被强杀，不会补写 `turn/end`，此时只能落到 `STALLED?`，分不清「死」与「等」。要区分需再加一路 `Get-Process`。
- 没确认 GUI 是否有 HTTP 端点可查状态，本方案只读磁盘 record。
- `.tmp/` 已被 `.gitignore:3` 忽略，本目录不进版本库；但**仍属一次性脚本，未纳入 CI**。
- `WAITING` 判不出编排器的意图：是主动等回调，还是它认为任务已收尾。只能确认它没异常终止。

## 7. 换目标会话

改 [watch.cjs](watch.cjs) 顶部的 `ROOT_ID`（以及 `SLUG`，如果工作目录变了）。子代理清单是从 `subagent/catalog` 自动解析的，**不用手工维护**。
