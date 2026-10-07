# tmp/ 删除清单（2026-10-06）

> **为什么删**：用户裁决「连证据与材料一起迁出后清空整个 tmp/」。
> 需入库的证据与材料已迁至 `docs/证据/`；本清单留档删除时的构成，供事后复核。
> **不可逆**：这些内容已不在任何版本控制中（`tmp/` 被 `.gitignore` 忽略）。

| 项 | 值 |
|---|---|
| 删除时间 | 2026-10-06 |
| 文件数 | 6976 |
| 合计 | 321.1 MB |

## 顶层构成

| 目录/文件 | MB | 文件数 |
|---|---:|---:|
| `_full2.log` | 0.01 | 1 |
| `_full2.xml` | 0.23 | 1 |
| `_full3.log` | 0 | 1 |
| `_full3.xml` | 0.23 | 1 |
| `_full4.log` | 0 | 1 |
| `_full4.xml` | 0.23 | 1 |
| `_fullsuite.log` | 0.01 | 1 |
| `_fullsuite.xml` | 0.23 | 1 |
| `_orchestrator-backup/` | 0.01 | 2 |
| `服务器选型-项目事实材料.md` | 0.04 | 1 |
| `项目功能介绍.md` | 0.01 | 1 |
| `design-render/` | 3.99 | 34 |
| `journey/` | 2.85 | 133 |
| `orch-final/` | 0.21 | 4 |
| `reviewer-T01/` | 193.19 | 2604 |
| `reviewer-T02/` | 5.84 | 157 |
| `reviewer-T02-visual/` | 0.19 | 11 |
| `reviewer-T03/` | 0.9 | 14 |
| `reviewer-T03-final/` | 1.05 | 29 |
| `reviewer-T03-r2/` | 0.01 | 3 |
| `reviewer-T03-r3/` | 0.3 | 12 |
| `reviewer-T04/` | 2.84 | 38 |
| `reviewer-T05/` | 3.81 | 74 |
| `reviewer-T06/` | 6.42 | 90 |
| `reviewer-T07/` | 1.22 | 26 |
| `reviewer-T07-r2/` | 1.21 | 25 |
| `reviewer-T10/` | 0.05 | 6 |
| `reviewer-T11/` | 0.1 | 7 |
| `reviewer-T11r2/` | 6.44 | 98 |
| `reviewer-T12/` | 29.11 | 2246 |
| `reviewer-T12r2/` | 0.32 | 18 |
| `reviewer-T13/` | 0.46 | 27 |
| `reviewer-T14/` | 0.14 | 11 |
| `reviewer-T15/` | 0.63 | 30 |
| `reviewer-T17/` | 0.23 | 5 |
| `reviewer-T18/` | 0.26 | 12 |
| `reviewer-T19/` | 0.03 | 10 |
| `reviewer-T20/` | 0.28 | 74 |
| `reviewer-T21/` | 0.02 | 9 |
| `reviewer-T22/` | 0.02 | 2 |
| `reviewer-T25/` | 0.04 | 11 |
| `reviewer-T27/` | 0.03 | 8 |
| `reviewer-T30/` | 0 | 5 |
| `reviewer-T31/` | 0.04 | 9 |
| `reviewer-T31-r3/` | 0.22 | 7 |
| `reviewer-T32/` | 0.48 | 23 |
| `reviewer-T33/` | 0.03 | 18 |
| `screenshots/` | 36.88 | 428 |
| `screenshots-r4-t02/` | 9.21 | 107 |
| `T04-private-dist-after/` | 0.96 | 3 |
| `T04-private-dist-before/` | 0.96 | 3 |
| `T10/` | 0.54 | 20 |
| `T11/` | 0.7 | 34 |
| `T11r2/` | 4.33 | 45 |
| `T11r2-head-todo.md` | 0.06 | 1 |
| `t12r2_drift/` | 0.49 | 21 |
| `T13_backend_documented.log` | 0.02 | 1 |
| `T13_backend_serve.log` | 0 | 1 |
| `T13_backend_serve2.log` | 0 | 1 |
| `T13_child.py` | 0 | 1 |
| `T13_parent.py` | 0 | 1 |
| `T13_probe.py` | 0 | 1 |
| `T13_probe2.py` | 0 | 1 |
| `T13_probe3.py` | 0 | 1 |
| `T13_probe4.py` | 0 | 1 |
| `T13-gfm-final.txt` | 0 | 1 |
| `T13-gfm-mutant.txt` | 0 | 1 |
| `T13-mutant-outside.md` | 0.07 | 1 |
| `T14/` | 0.18 | 29 |
| `T17/` | 0.28 | 58 |
| `t27/` | 0.83 | 51 |
| `t28/` | 0.11 | 29 |
| `t30/` | 0.03 | 5 |
| `t31/` | 0.54 | 65 |
| `t32/` | 0.55 | 52 |
| `t33/` | 0.25 | 53 |
| `t33r2/` | 0.1 | 58 |

## 已迁出（不随删除丢失）

| 原路径 | 新路径 |
|---|---|
| `tmp/design-render/{render.mjs,README.md,inventory.json,page-annotated.pins.json}` | `docs/证据/design-render/` |
| `tmp/T17/{probe_redis_semantics.py,ablation_st15.err.log}` | `docs/证据/probes/` |
| `tmp/T11/{serve.py,run-real.ps1,fuzz-5xx.cjs,repro-embedder.py}` | `docs/证据/probes/` |
| `tmp/t27/step0-sse-frames.txt` | `docs/证据/probes/` |
| `tmp/{服务器选型-项目事实材料.md,项目功能介绍.md,T11r2-head-todo.md,T13-mutant-outside.md}` | `docs/证据/materials/` |
| `tmp/_orchestrator-backup/{RESTORE.md,conftest.py}` | `docs/证据/materials/orchestrator-backup-*` |

## 未迁出（按判据属可重新生成）

- `reviewer-*` / `screenshots*` / `journey` / `t2x` / `T1x` 下的 Playwright 截图、
  trace、JSON 报告：由 e2e 重跑生成（`apps/web/e2e` 的 `paths.ts` 会在运行时 `mkdir`）。
- `tmp/design-render/{sections,states}/*.png` 与 `page-annotated*.png`（3.9 MB / 30 张）：
  按 `docs/证据/design-render/README.md` 定义是可重新渲染产物；渲染器已入库，真源哈希见 `inventory.json`（已核对与当前 `docs/design/` 一致）。
- `.tmp/acceptance_section1.py`、`.tmp/probe_sse_location.py`、
  `.tmp/dev-orchestrator/20261002-001/**` 的受引用件已迁出；其余为编排过程产物。

