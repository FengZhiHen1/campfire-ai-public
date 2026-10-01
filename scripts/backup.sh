#!/usr/bin/env bash
#
# 备份：PostgreSQL（业务数据 + 会话 + SuperTokens 表）与 FalkorDB（长期记忆图）。
#
# 用法：
#   scripts/backup.sh --help
#   scripts/backup.sh --out-dir /var/backups/campfire
#   scripts/backup.sh --out-dir ./backups --compose-file docker-compose.prod.yml --env-file .env.prod
#
# ## 为什么需要它
#
# 这个应用同时保存三类必须能恢复的数据：
#
#   PostgreSQL  账号、会话归属、档案、资料与案例、RAG 节点、删除墓碑、待处理记录
#               （**SuperTokens core 的表也在同一个库里**）
#   FalkorDB    Graphiti 长期记忆（按账号分图）
#   Redis       队列与短期状态——见下方「Redis 为什么要备份」
#
# 「能启动」不等于「可生产运行」：没有可验证的备份与恢复演练，一次误操作就是不可逆的
# 数据丢失。因此本脚本的产物必须能被 `scripts/restore.sh` 读回，且脚本自己会校验。
#
# ## 设计取舍
#
# 1. **用 `pg_dump` 自定义格式（`-Fc`）而不是文件系统快照卷**。快照要停容器（否则
#    拷到的是崩溃一致但未必可恢复的状态），且与 PostgreSQL 主版本强绑定；`pg_dump`
#    的逻辑转储可跨小版本恢复，也能单表恢复。
# 2. **FalkorDB 用 `BGSAVE` + 拷贝 `dump.rdb`**。它是 Redis 分支，`SAVE`/`BGSAVE`
#    是它唯一的持久化机制。先 `BGSAVE` 再等 `LASTSAVE` 变化，保证拷到的是**已落盘**的
#    快照，而不是正在写的文件。
# 3. **Redis 也要备份**（见 `--skip-redis` 可关）。虽然「真相源不在队列」，但
#    `pending_write` 的投递与运行缓冲（runbus）在 Redis 里；丢 Redis 后待处理记录会靠
#    兜底扫描重投（设计如此），但**在途的运行会丢**，且要等最多一个扫描周期。
#    代价很低（RDB 很小），故默认包含。
# 4. **产物带 sha256**。备份的价值在于「能确认它完整」——没有校验和的备份，恢复时
#    才发现损坏就太晚了。`restore.sh` 会先核对。
#
# ## 保留周期
#
# 本脚本**不删除任何东西**。保留策略属于运维决策（见 docs/运维/发布与回滚.md 的建议），
# 且自动删除是不可逆操作——一个删错保留期的成本远高于多存几份。

set -euo pipefail

# --- 参数 ---------------------------------------------------------------

OUT_DIR=""
COMPOSE_FILE="docker-compose.yml"
ENV_FILE=""
PROJECT_NAME=""
SKIP_REDIS="0"
COMPOSE_CMD=""

usage() {
    cat <<'EOF'
用法：backup.sh --out-dir <目录> [选项]

必需：
  --out-dir <目录>          备份产物写入目录（会被创建）

可选：
  --compose-file <文件>     compose 文件（默认 docker-compose.yml；
                            生产用 docker-compose.prod.yml）
  --env-file <文件>         compose 环境变量文件（生产用 .env.prod）
  --project-name <名>       compose 项目名（默认由 compose 文件推导）
  --skip-redis              跳过 Redis 备份（见脚本内「Redis 为什么要备份」）
  -h, --help                显示本说明

产物（`<out-dir>/<UTC 时间戳>/`）：
  postgres.dump              PostgreSQL 自定义格式转储（pg_restore 可读）
  falkordb-dump.rdb          FalkorDB 快照
  redis-dump.rdb             Redis 快照（除非 --skip-redis）
  manifest.txt               每项的大小、sha256 与来源容器
  SHA256SUMS                 校验和清单（供 restore.sh 核对）

退出码：0 成功；1 参数或环境错误；2 备份中某一步失败。
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --out-dir)      OUT_DIR="${2:-}"; shift 2 ;;
        --compose-file) COMPOSE_FILE="${2:-}"; shift 2 ;;
        --env-file)     ENV_FILE="${2:-}"; shift 2 ;;
        --project-name) PROJECT_NAME="${2:-}"; shift 2 ;;
        --skip-redis)   SKIP_REDIS="1"; shift ;;
        -h|--help)      usage; exit 0 ;;
        *) echo "未知参数：$1" >&2; usage >&2; exit 1 ;;
    esac
done

if [ -z "$OUT_DIR" ]; then
    echo "错误：必须给 --out-dir（产物写哪里是运维决策，不设默认值）" >&2
    usage >&2
    exit 1
fi

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "错误：找不到 compose 文件 $COMPOSE_FILE" >&2
    exit 1
fi

# `docker compose` 的 v2 子命令形式。参数按需拼，不用数组（POSIX sh 兼容性）。
compose() {
    # shellcheck disable=SC2086
    docker compose -f "$COMPOSE_FILE" ${ENV_FILE:+"--env-file" "$ENV_FILE"} ${PROJECT_NAME:+"--project-name" "$PROJECT_NAME"} "$@"
}

if ! docker compose version >/dev/null 2>&1; then
    echo "错误：需要 docker compose v2（实测本机 docker 29.x 自带）" >&2
    exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT_DIR/$STAMP"
mkdir -p "$DEST"

# 把 env 文件里的密码读进**本脚本自己的环境**（2026-10-01 真机踩到的第二个缺陷）。
#
# ⚠️ `--env-file` 只喂给 `docker compose`，**不会**导出到脚本进程。此前 `falkor_cli`
# 判断的是 `${FALKORDB_PASSWORD:-}`，而那个变量在本脚本里**始终为空**，于是永远走
# 「不带密码」的分支 → `redis-cli` 返回 `NOAUTH`。
#
# 后果很隐蔽：`NOAUTH Authentication required.` 这行文本被当成 `LASTSAVE` 的值，
# 而 `redis-cli` 在未认证时**退出码仍是 0**（实测），所以：
#   - 守卫 `if ! falkor_cli PING` 抓不到（退出码 0，看起来成功）；
#   - `before` 与轮询到的 `now` 是同一行错误文本，永远相等；
#   → 必然报「30 秒内未完成 BGSAVE」，**看起来像持久化卡住，实际是没认证**。
#
# 用 `set -a` + `.` 把文件里的变量导出（与 compose 读的是同一个文件，不会漂移）；
# 文件不存在就跳过——后续的 PING 守卫会以清晰的报错兜住。
if [ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "./$ENV_FILE" 2>/dev/null || . "$ENV_FILE" 2>/dev/null || true
    set +a
fi

echo "备份目录：$DEST"
echo

# --- PostgreSQL ---------------------------------------------------------

# 容器名从 compose 取，不硬编码：dev 与 prod 的容器名可能不同（本项目两者都叫
# campfire-postgres，但用 compose 查询更稳）。
PG_SERVICE="postgres"
echo "[1/3] PostgreSQL：pg_dump（自定义格式）"

# `-Fc` 自定义格式：可被 `pg_restore` 选择性恢复，且默认压缩。
# `--no-owner --no-privileges`：恢复目标机的角色名可能与源不同，带上属主会让恢复失败。
#
# 库名从容器环境读（POSTGRES_DB），避免在脚本里写死第二处真相。
if ! compose exec -T "$PG_SERVICE" sh -c \
        'pg_dump -U "${POSTGRES_USER:-campfire}" -d "${POSTGRES_DB:-campfire}" -Fc --no-owner --no-privileges' \
        > "$DEST/postgres.dump"; then
    echo "错误：pg_dump 失败" >&2
    exit 2
fi

# 立刻校验产物可被 pg_restore 读取——这是「备份真的可用」的第一道证据。
# 没有这一步，损坏的转储要到恢复时才发现。
if ! compose exec -T "$PG_SERVICE" pg_restore --list > /dev/null < "$DEST/postgres.dump" 2>/dev/null; then
    # 某些镜像的 pg_restore 对 stdin 支持不同，回落到容器内直接读文件的方式再验一次。
    echo "  提示：pg_restore --list 读 stdin 失败，改用容器内校验"
    if ! compose exec -T "$PG_SERVICE" sh -c 'cat > /tmp/verify.dump' < "$DEST/postgres.dump" \
        || ! compose exec -T "$PG_SERVICE" pg_restore --list /tmp/verify.dump > /dev/null; then
        echo "错误：转储无法被 pg_restore 解析——不要把它当作可用备份" >&2
        exit 2
    fi
    compose exec -T "$PG_SERVICE" rm -f /tmp/verify.dump
fi
echo "      $(wc -c < "$DEST/postgres.dump" | tr -d ' ') 字节，pg_restore 可解析"

# --- FalkorDB -----------------------------------------------------------

FALKOR_SERVICE="falkordb"
echo "[2/3] FalkorDB：BGSAVE + 拷贝 dump.rdb"

# FalkorDB 是 Redis 分支，生产必须设密码（见 compose 的 `REDIS_ARGS: --requirepass`）。
#
# **这是实测踩到的缺陷**（2026-10-01 第一次在生产上跑）：此前这里的四条 `redis-cli`
# 调用都没带密码，只在本地 dev 验证过——而 dev 的 FalkorDB 没有密码，所以「通过」了。
# 生产上不带密码得到的是：
#     NOAUTH Authentication required.
# 于是 `before` 与轮询到的 `now` 都是这行同样的错误文本、永远相等，
# 脚本必然报「30 秒内未完成 BGSAVE」——**看起来像持久化卡住，实际是没通过认证**。
#
# 密码来源：优先 `FALKORDB_PASSWORD` 环境变量（.env.prod / compose 都会注入），
# 没有则回调 `docker compose exec` 到容器里读它自己的 `$FALKORDB_PASSWORD`
# （compose 现在显式传给容器，见 docker-compose.prod.yml 的说明）。
falkor_cli() {
    if [ -n "${FALKORDB_PASSWORD:-}" ]; then
        compose exec -T "$FALKOR_SERVICE" redis-cli -a "$FALKORDB_PASSWORD" --no-auth-warning "$@"
    elif [ -n "${REDIS_PASSWORD:-}" ]; then
        # 兜底：compose 文件里若只给了 REDIS_PASSWORD（dev 形态），仍能工作。
        compose exec -T "$FALKOR_SERVICE" redis-cli -a "$REDIS_PASSWORD" --no-auth-warning "$@"
    else
        compose exec -T "$FALKOR_SERVICE" redis-cli "$@"
    fi
}

# 先探一次，把「未认证」这类问题**在开始轮询之前**就报出来，而不是伪装成超时。
#
# ⚠️ 不能只看退出码（2026-10-01 真机踩到）：`redis-cli` 在未认证时打印
# `NOAUTH Authentication required.` 但**退出码仍是 0**（实测），因此
# `if ! falkor_cli PING` 这个写法永远为假，守卫形同虚设。改为**检查输出内容**是否
# 恰好是 `PONG`——这才是「认证通过且服务可用」的判据。
falkor_ping="$(falkor_cli PING 2>&1 | tr -d '\r' | tail -n 1)"
if [ "$falkor_ping" != "PONG" ]; then
    echo "错误：FalkorDB PING 未返回 PONG（实际：$falkor_ping）" >&2
    echo "      常见原因：FALKORDB_PASSWORD 与容器内不一致，或 env 文件未被读到。" >&2
    echo "      注意 redis-cli 未认证时退出码为 0，所以这里判的是**输出**而非退出码。" >&2
    exit 2
fi

# 先触发后台保存，再等 LASTSAVE 变化——保证拷到的是**已落盘**的快照，
# 而不是一个正在被写的文件（那会得到一个损坏的 RDB）。
before="$(falkor_cli LASTSAVE | tr -d '\r')"
falkor_cli BGSAVE > /dev/null

saved=""
for _ in $(seq 1 30); do
    sleep 1
    now="$(falkor_cli LASTSAVE | tr -d '\r')"
    if [ "$now" != "$before" ]; then saved="$now"; break; fi
done

if [ -z "$saved" ]; then
    echo "错误：FalkorDB 在 30 秒内未完成 BGSAVE（LASTSAVE 未变化）" >&2
    exit 2
fi
echo "      BGSAVE 完成（LASTSAVE=$saved）"

# 路径从 Redis 自己问，不硬编码。**这是实测踩到的**（2026-10-01）：FalkorDB 镜像的
# 数据目录是 `/var/lib/falkordb/data`，不是 Redis 惯用的 `/data`——按 `/data` 读会得到
# `cat: can't open '/data/dump.rdb': No such file or directory`，而 BGSAVE 明明成功了。
# 用 `CONFIG GET dir` 问出来的路径对 dev 与 prod 两种镜像都成立，也不会随上游改路径而失效。
falkor_dir="$(falkor_cli CONFIG GET dir | tail -n 1 | tr -d '\r')"
falkor_file="$(falkor_cli CONFIG GET dbfilename | tail -n 1 | tr -d '\r')"
if [ -z "$falkor_dir" ] || [ -z "$falkor_file" ]; then
    echo "错误：无法从 FalkorDB 取得持久化路径（CONFIG GET dir/dbfilename 为空）" >&2
    exit 2
fi
echo "      持久化路径：$falkor_dir/$falkor_file"

# 从容器里把 RDB 取出来。用 `cat` 经 stdout 而不是 `docker cp`：不必知道容器 ID，
# 且 compose 已经解析了服务名。
if ! compose exec -T "$FALKOR_SERVICE" cat "$falkor_dir/$falkor_file" > "$DEST/falkordb-dump.rdb"; then
    echo "错误：读取 FalkorDB 快照失败（$falkor_dir/$falkor_file）" >&2
    exit 2
fi
echo "      $(wc -c < "$DEST/falkordb-dump.rdb" | tr -d ' ') 字节"

# --- Redis --------------------------------------------------------------

if [ "$SKIP_REDIS" = "1" ]; then
    echo "[3/3] Redis：按要求跳过"
else
    REDIS_SERVICE="redis"
    echo "[3/3] Redis：BGSAVE + 拷贝 dump.rdb"

    # Redis 可能配了密码（生产 compose 强制要求）。dev 那份没有密码，
    # 因此两种情形都要能跑：有 REDIS_PASSWORD 就带 `-a`。
    redis_cli() {
        if [ -n "${REDIS_PASSWORD:-}" ]; then
            compose exec -T "$REDIS_SERVICE" redis-cli -a "$REDIS_PASSWORD" --no-auth-warning "$@"
        else
            compose exec -T "$REDIS_SERVICE" redis-cli "$@"
        fi
    }

    rbefore="$(redis_cli LASTSAVE | tr -d '\r')"
    redis_cli BGSAVE > /dev/null
    rsaved=""
    for _ in $(seq 1 30); do
        sleep 1
        rnow="$(redis_cli LASTSAVE | tr -d '\r')"
        if [ "$rnow" != "$rbefore" ]; then rsaved="$rnow"; break; fi
    done
    if [ -z "$rsaved" ]; then
        echo "警告：Redis 未在 30 秒内完成 BGSAVE，跳过 Redis（其余备份有效）" >&2
    else
        # 与 FalkorDB 同一处置：路径问 Redis 自己，不硬编码（理由见上面 FalkorDB 段）。
        redis_dir="$(redis_cli CONFIG GET dir | tail -n 1 | tr -d '\r')"
        redis_file="$(redis_cli CONFIG GET dbfilename | tail -n 1 | tr -d '\r')"
        if compose exec -T "$REDIS_SERVICE" cat "$redis_dir/$redis_file" > "$DEST/redis-dump.rdb"; then
            echo "      完成（LASTSAVE=$rsaved），$(wc -c < "$DEST/redis-dump.rdb" | tr -d ' ') 字节"
        else
            echo "警告：读取 Redis 快照失败（$redis_dir/$redis_file），跳过（其余备份有效）" >&2
            rm -f "$DEST/redis-dump.rdb"
        fi
    fi
fi

# --- 校验和与清单 -------------------------------------------------------

echo
echo "生成校验和与清单"

# 只对实际存在的产物算校验和。
( cd "$DEST" && for f in *.dump *.rdb; do
    [ -f "$f" ] || continue
    if command -v sha256sum > /dev/null 2>&1; then sha256sum "$f"; else shasum -a 256 "$f"; fi
  done > SHA256SUMS )

{
    echo "备份时间（UTC）：$STAMP"
    echo "compose 文件：$COMPOSE_FILE"
    echo "env 文件：${ENV_FILE:-（未指定）}"
    echo "compose 项目：${PROJECT_NAME:-（由 compose 推导）}"
    echo
    echo "产物："
    for f in "$DEST"/*; do
        [ -f "$f" ] || continue
        printf '  %-24s %10s 字节\n' "$(basename "$f")" "$(wc -c < "$f" | tr -d ' ')"
    done
    echo
    echo "校验和（SHA256SUMS）："
    sed 's/^/  /' "$DEST/SHA256SUMS"
    echo
    echo "恢复：scripts/restore.sh --from $DEST [--yes]"
} > "$DEST/manifest.txt"

# sha256 之后写 manifest，再对 manifest 之外的文件重算一次会被它自己改变，
# 因此 manifest 不进 SHA256SUMS（它是描述性文件，不是数据）。
cat "$DEST/manifest.txt"
echo
echo "备份完成：$DEST"
echo
echo "⚠️ 请把产物复制到**另一台机器**。同一块盘上的备份在磁盘故障时一起丢——"
echo "   这不是备份。见 docs/运维/发布与回滚.md 的「异地副本」一节。"
