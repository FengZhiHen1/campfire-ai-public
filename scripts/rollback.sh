#!/usr/bin/env bash
#
# 回滚：把应用切回上一个已发布的镜像版本。
#
# 用法：
#   scripts/rollback.sh --help
#   scripts/rollback.sh --target-sha <12 位 SHA> --host deploy@example.com --path /opt/campfire --yes
#
# ## 这个脚本做什么、不做什么
#
# **做**：把目标机 `.env.prod` 里的 `IMAGE_TAG` 改回指定版本，重新 `compose up -d`，
# 然后轮询 `/readyz` 确认真的起来了。
#
# **不做**：数据库 downgrade。这是刻意的，理由见 `docs/运维/发布与回滚.md`：
# 迁移里可能有删列/改类型（不可逆），而自动 downgrade 会**丢数据**。回滚的正确形态是
# 「新代码向后兼容一版」，因此迁移也必须向后兼容一版——这样回滚只需换镜像。
#
# ## 为什么回滚要单列一个脚本而不是「再跑一次 deploy」
#
# 发布是「验证过的动作」，回滚是「出问题时的动作」。后者的使用场景不同：
# 执行者在压力下操作、且时间敏感。因此本脚本：
#
#   - 只做最少的事（改 tag、重启、验证），不做镜像构建
#   - 不要求备份（此刻可能没有时间；但会打印提示）
#   - 每一步都打印它做了什么，便于事后追责与复盘
#   - **需要 `--yes`**：它会改变生产运行状态
#
# ## 前置条件（脚本会校验）
#
#   目标机的 compose 目录里必须有 `.env.prod`，且里面有一行 `IMAGE_TAG=...`。
#   该行由 deploy.yml 维护（`sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=<sha>/'`），因此
#   第一次发布之后它必定存在。

set -euo pipefail

TARGET_SHA=""
HOST=""
PATH_DIR=""
COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env.prod"
SSH_KEY=""
ASSUME_YES="0"
#: 轮询上界：40 次 × 3 秒 = 120 秒，与 deploy.yml 的发布验证一致。
PROBE_ATTEMPTS="40"

usage() {
    cat <<'EOF'
用法：rollback.sh --target-sha <SHA> --host <用户@主机> --path <目录> [选项]

必需：
  --target-sha <SHA>        要回退到的镜像 tag（通常是上一个提交的 SHA 前 12 位）
  --host <用户@主机>         SSH 目标
  --path <目录>             目标机上的 compose 目录（含 docker-compose.prod.yml 与 .env.prod）

可选：
  --ssh-key <文件>          SSH 私钥
  --compose-file <文件>     目标机上的 compose 文件名（默认 docker-compose.prod.yml）
  --env-file <文件>         目标机上的 env 文件名（默认 .env.prod）
  --yes                     确认执行（**不加即为演练**：只打印将做什么）
  -h, --help                显示本说明

如何知道有哪些可回退的版本：
  在目标机上 `grep IMAGE_TAG .env.prod`（当前版本），历史版本见 GHCR 的镜像列表：
  https://github.com/<owner>/<repo>/pkgs/container/<repo>%2Fapi

⚠️ 不改数据库。迁移必须向后兼容一版，理由见 docs/运维/发布与回滚.md。
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --target-sha)   TARGET_SHA="${2:-}"; shift 2 ;;
        --host)         HOST="${2:-}"; shift 2 ;;
        --path)         PATH_DIR="${2:-}"; shift 2 ;;
        --ssh-key)      SSH_KEY="${2:-}"; shift 2 ;;
        --compose-file) COMPOSE_FILE="${2:-}"; shift 2 ;;
        --env-file)     ENV_FILE="${2:-}"; shift 2 ;;
        --yes)          ASSUME_YES="1"; shift ;;
        -h|--help)      usage; exit 0 ;;
        *) echo "未知参数：$1" >&2; usage >&2; exit 1 ;;
    esac
done

missing=""
[ -n "$TARGET_SHA" ] || missing="$missing --target-sha"
[ -n "$HOST" ] || missing="$missing --host"
[ -n "$PATH_DIR" ] || missing="$missing --path"
if [ -n "$missing" ]; then
    echo "错误：缺少必需参数：$missing" >&2
    usage >&2
    exit 1
fi

# tag 形状校验：deploy.yml 用提交 SHA 前 12 位。提前拦住明显错的输入，
# 避免「回滚到一个不存在的镜像」在生产上才发现。
case "$TARGET_SHA" in
    *[!0-9a-f]*|"")
        echo "错误：--target-sha 应为小写十六进制（提交 SHA 前 12 位），收到：$TARGET_SHA" >&2
        exit 1 ;;
esac

ssh_cmd() {
    # shellcheck disable=SC2086
    ssh ${SSH_KEY:+-i "$SSH_KEY"} "$HOST" "$@"
}

# --- 探测当前状态（只读）-------------------------------------------------

echo "目标：$HOST:$PATH_DIR"
echo "目标版本：$TARGET_SHA"
echo

echo "读取当前状态（只读）"
current="$(
    ssh_cmd "grep '^IMAGE_TAG=' '$PATH_DIR/$ENV_FILE' 2>/dev/null | head -n 1" || true
)"
if [ -z "$current" ]; then
    echo "错误：读不到 $PATH_DIR/$ENV_FILE 里的 IMAGE_TAG。" >&2
    echo "      该行由 deploy.yml 在首次发布时写入；若这是第一次部署，没有可回滚的版本。" >&2
    exit 1
fi
echo "  当前：$current"
echo "  目标：IMAGE_TAG=$TARGET_SHA"

if [ "$current" = "IMAGE_TAG=$TARGET_SHA" ]; then
    echo
    echo "目标版本与当前版本相同——无需回滚。"
    exit 0
fi

# --- 演练 ---------------------------------------------------------------

if [ "$ASSUME_YES" != "1" ]; then
    echo
    echo "=== 演练模式（未加 --yes）==="
    echo "将要执行（**尚未改变任何东西**）："
    echo "  1. 在 $HOST:$PATH_DIR/$ENV_FILE 把 $current 改为 IMAGE_TAG=$TARGET_SHA"
    echo "  2. 拉取该版本镜像：docker compose pull"
    echo "  3. 重启：docker compose up -d --no-build"
    echo "  4. 轮询 /readyz 直到 200（最多 120 秒）"
    echo
    echo "⚠️ 不改数据库（迁移必须向后兼容一版）。"
    echo "   确认后重跑并加 --yes。"
    exit 0
fi

echo
echo "=== 执行回滚（--yes 已给）==="

# --- 1. 换 tag ----------------------------------------------------------

echo "[1/4] 写入 IMAGE_TAG=$TARGET_SHA"
# 先备份 .env.prod：回滚本身也可能需要被回滚。用固定后缀避免留下多份难辨认的副本。
ssh_cmd "cd '$PATH_DIR' && cp -n '$ENV_FILE' '$ENV_FILE.before-rollback' 2>/dev/null || true && \
         sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=$TARGET_SHA/' '$ENV_FILE' && \
         grep '^IMAGE_TAG=' '$ENV_FILE'"

# --- 2. 拉镜像 ----------------------------------------------------------

echo "[2/4] 拉取镜像"
# 这一步失败通常意味着 tag 不存在（写错了 SHA）。此时**还没有重启服务**，
# 生产仍在旧版本上跑——失败是安全的，脚本退出即可。
if ! ssh_cmd "cd '$PATH_DIR' && docker compose -f '$COMPOSE_FILE' --env-file '$ENV_FILE' pull"; then
    echo "错误：拉取镜像失败——tag '$TARGET_SHA' 可能不存在。" >&2
    echo "      生产仍在原版本上运行（尚未重启）。" >&2
    echo "      恢复 .env.prod：$PATH_DIR/$ENV_FILE.before-rollback" >&2
    exit 2
fi

# --- 3. 重启 ------------------------------------------------------------

echo "[3/4] 重启"
# `--no-build` 是刻意的（2026-10-01 真机踩到后加的，与 deploy.yml 同一理由）：
# compose 里 web/api 同时有 `build:` 与 `image:`，而发布目录只放 compose 与
# infrastructure、**没有源码**。默认行为下若镜像没拉到，`up -d` 会回落到本地构建——
# 要么失败，要么更糟：复用遗留的同名镜像，让「回滚成功」的其实不是目标版本。
# 回滚路径上尤其不能这样：它的全部意义就是确定地回到某个已知版本。
ssh_cmd "cd '$PATH_DIR' && docker compose -f '$COMPOSE_FILE' --env-file '$ENV_FILE' up -d --no-build"

# --- 4. 验证 ------------------------------------------------------------

echo "[4/4] 验证 /readyz"
# 与 deploy.yml 用同一条判据（/readyz 而不是 /livez）：后者只看进程活着，
# 一个「装配失败、核心端点必回 503」的版本在它眼里是健康的。
if ssh_cmd "cd '$PATH_DIR' && for i in \$(seq 1 $PROBE_ATTEMPTS); do
        code=\$(docker compose -f '$COMPOSE_FILE' exec -T api \
            curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/readyz || echo 000)
        if [ \"\$code\" = '200' ]; then echo \"readyz 200（第 \$i 次）\"; exit 0; fi
        echo \"第 \$i 次：\$code\"; sleep 3
    done
    echo '回滚后 /readyz 仍未就绪' >&2
    docker compose -f '$COMPOSE_FILE' logs --tail 40 api >&2 || true
    exit 1"; then
    echo
    echo "回滚完成：已回到 $TARGET_SHA，且 /readyz 返回 200。"
    echo
    echo "事后必做（不要跳过）："
    echo "  1. 记录：时间、从哪个版本回退到哪个版本、触发原因、执行人"
    echo "  2. 查因：在**开发机**上复现问题，不要在生产的容器里改代码"
    echo "  3. 复核数据：若有迁移已执行且新版本写过新列，旧代码可能读不懂那些行——"
    echo "     确认受影响的业务面（见 docs/运维/发布与回滚.md 的「迁移与回滚」）"
else
    echo
    echo "回滚后服务仍未就绪。" >&2
    echo "  当前 IMAGE_TAG=$TARGET_SHA，.env.prod 的改动前副本在同目录 .before-rollback" >&2
    echo "  下一步见 docs/运维/发布与回滚.md 的「回滚也失败」一节。" >&2
    exit 3
fi
