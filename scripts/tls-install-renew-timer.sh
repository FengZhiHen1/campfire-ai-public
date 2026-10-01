#!/usr/bin/env bash
#
# 安装证书自动续期的 systemd timer（每日跑一次续期脚本）。
#
# 用法：scripts/tls-install-renew-timer.sh
#
# ## 为什么是每日
#
# `certbot renew` 自身只在「距到期 30 天内」才动作，因此每日跑不会造成重复签发，
# 却能把「忘记续期」的时间窗压到最短。Let's Encrypt 的速率限制是**每周 5 次成功签发**，
# 而 30 天窗口内每日执行最多命中 1 次真实签发，远离该限制。
#
# ## 为什么用 timer 而不是 cron
#
# `Persistent=true` 让机器在关机期间错过的时间点会在恢复后补跑——对「小机器偶尔
# 重启」的场景这是关键差别。另外 timer 的输出进 journald，出问题能查。
#
# ## 这个脚本为什么存在（而不是让人手敲三条 systemd 命令）
#
# 手敲容易漏掉 `daemon-reload`、或者把 unit 名写错而 systemd 静默不认；更要紧的是
# 「装完了但 timer 没启用」这种状态**看起来是装好了**。因此这里装完**立刻验证**
# 并打印下次触发时间。
set -euo pipefail

REPO_SCRIPT="/opt/campfire/scripts/tls-renew.sh"
UNIT_DIR="/etc/systemd/system"

if [ ! -f "$REPO_SCRIPT" ]; then
  echo "错误：找不到 $REPO_SCRIPT" >&2
  echo "      请先把仓库里的 scripts/ 同步到部署目录。" >&2
  exit 1
fi
sudo chmod +x "$REPO_SCRIPT"

echo "=== 写入 systemd unit ==="

sudo tee "$UNIT_DIR/campfire-tls-renew.service" >/dev/null <<EOF
[Unit]
Description=Campfire-AI 证书续期（Let's Encrypt）
Documentation=https://github.com/FengZhiHen1/Campfire-AI
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
# 用 root 执行：certbot 容器写证书目录、以及 docker exec reload 都需要。
ExecStart=$REPO_SCRIPT
# 续期失败要留下痕迹（默认 oneshot 失败只是退出码，日志会进 journal）。
StandardOutput=journal
StandardError=journal
EOF

sudo tee "$UNIT_DIR/campfire-tls-renew.timer" >/dev/null <<'EOF'
[Unit]
Description=每日检查 Campfire-AI 证书续期

[Timer]
# 每天跑一次；随机延迟 0-30 分钟，避免与其它整点任务撞在一起。
OnCalendar=daily
RandomizedDelaySec=30min
# 关机期间错过的执行点，开机后补跑——小机器重启是常态。
Persistent=true
Unit=campfire-tls-renew.service

[Install]
WantedBy=timers.target
EOF

echo "=== 启用 timer ==="
# `daemon-reload` 不能省：新写的 unit 不 reload 则 systemd 不认，enable 会失败。
sudo systemctl daemon-reload
sudo systemctl enable --now campfire-tls-renew.timer

echo
echo "=== 验证（装完不看一眼等于没装）==="
sudo systemctl list-timers campfire-tls-renew.timer --no-pager || true
echo
if systemctl is-active --quiet campfire-tls-renew.timer; then
  echo "timer 已启用并在运行。"
else
  echo "错误：timer 未处于 active 状态，请查看 systemctl status campfire-tls-renew.timer" >&2
  exit 1
fi

echo
echo "手动演练一次（不会真的换证书）："
echo "  sudo systemctl start campfire-tls-renew.service    # 或脚本加 --dry-run"
echo "查看日志："
echo "  journalctl -u campfire-tls-renew.service --since today"
