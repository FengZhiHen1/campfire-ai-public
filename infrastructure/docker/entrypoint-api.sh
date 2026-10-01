#!/bin/sh
# API / Worker 容器入口：可选地跑迁移，然后执行传入的命令。
#
# 为什么把「跑迁移」做成入口的一个开关，而不是写死在 Dockerfile 的 CMD 里：
#
# - HTTP 与 Worker 共用同一个镜像。迁移只该由**一个**角色执行——两个容器同时
#   `alembic upgrade head` 会并发改 schema，而 Alembic 的版本表并不为此加锁。
#   因此默认由 HTTP 容器执行（`RUN_MIGRATIONS=1`），Worker 容器设为 0。
# - 发布流程（CD）需要「先迁移、后切换流量」，所以迁移必须是可单独触发的动作，
#   而不是嵌在启动里无法单独调用的黑盒。CD 里直接
#   `docker compose run --rm api alembic upgrade head` 即可（本脚本也支持）。
#
# 为什么失败即退出（`set -e`）：schema 与代码不匹配时，进程能起来但每个请求都错，
# 那是最难排查的状态。宁可不启动，让编排层看到明确的失败。
set -eu

# POSIX sh（本镜像基于 debian slim，/bin/sh 是 dash），因此不用 bash 专有语法。
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "[entrypoint] 执行数据库迁移：alembic upgrade head" >&2
    # 必须在仓库根执行：alembic.ini 的 script_location 是
    # `%(here)s/apps/api/migrations`，而 `%(here)s` 解析的是 ini 文件所在目录。
    # 从 apps/api 里跑会报 `No 'script_location' key found`（实测）。
    alembic upgrade head
    echo "[entrypoint] 迁移完成" >&2
fi

# 等依赖就绪不是本脚本的职责：compose 的 depends_on + healthcheck 已经表达了这个顺序，
# 在应用里再写一轮重试会制造第二处真相，且会在「依赖真的坏了」时掩盖成超时。
echo "[entrypoint] 启动：$*" >&2
exec "$@"
