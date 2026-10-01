#!/usr/bin/env bash
#
# 续期 Let's Encrypt 证书，并在证书真的更新后 reload nginx。
#
# 用法：
#   scripts/tls-renew.sh            实际续期
#   scripts/tls-renew.sh --dry-run  演练（向 ACME 真实校验，但不落盘证书）
#
# ## 为什么需要它
#
# `scripts/tls-issue-cert.sh` 只负责**首次签发**。证书 90 天有效，到期不续期就是
# 站点全站证书过期——浏览器直接拦截，比「证书没配」更糟（后者至少还能显式用 HTTP）。
# 2026-10-01 首次部署时未配置任何自动续期，这是一个**已知缺口**，本脚本补上它。
#
# ## 设计取舍
#
# 1. **用 systemd timer 而不是 cron**。timer 有 `Persistent=true`（机器关机错过时间点
#    后会补跑）、有 `journalctl` 可查、能设随机延迟避免整点尖峰。cron 三者都弱。
#
# 2. **`renew` 而不是重新 `certonly`**。`renew` 只在「距到期 30 天内」才动作，
#    因此可以放心地每日跑；`certonly --force` 会每次真签，容易撞 Let's Encrypt 的
#    速率限制（同一域名每周 5 次）。
#
# 3. **只在校验证书真的变了才 reload**。证书没变还 reload 是无谓中断；
#    而**变了不 reload 则等于没续**——nginx 会一直加载启动时读入的旧证书，
#    直到有人重启它。这是自动续期最常见的失效方式（脚本成功、站点仍过期）。
#
# 4. **续期后校验新证书确实可读**。避免「续了但 nginx 配置指向的路径不对」。
set -euo pipefail
cd /opt/campfire

DOMAIN="campfire.wenran.me"
CRT_DIR="/opt/campfire/infrastructure/nginx/ssl"
WEBROOT_HOST="/opt/campfire/certbot-www"
DRY_RUN="${1:-}"

# 记录续期前的证书指纹，用于判断是否真的更新了。
cert_fingerprint() {
  sudo openssl x509 -in "$CRT_DIR/live/$DOMAIN/fullchain.pem" -noout -fingerprint -sha256 2>/dev/null \
    | cut -d= -f2 || echo "none"
}
BEFORE="$(cert_fingerprint)"

echo "=== 续期前证书指纹 ==="
echo "  $BEFORE"

echo
echo "=== 运行 certbot renew${DRY_RUN:+（演练）} ==="
# certbot 容器以 root 运行；证书目录属 root，因此这里整段用 sudo。
# `--webroot` 与其路径要与首次签发一致，否则挑战文件写不到 nginx 能读的位置。
if [ "$DRY_RUN" = "--dry-run" ]; then
  sudo docker run --rm \
    -v "$CRT_DIR:/etc/letsencrypt" \
    -v "$WEBROOT_HOST:/var/www/certbot" \
    certbot/certbot renew --webroot -w /var/www/certbot --dry-run
  echo
  echo "演练完成：上面的 '模拟续期成功' 才表示自动续期链路可用。"
  exit 0
fi

sudo docker run --rm \
  -v "$CRT_DIR:/etc/letsencrypt" \
  -v "$WEBROOT_HOST:/var/www/certbot" \
  certbot/certbot renew --webroot -w /var/www/certbot

AFTER="$(cert_fingerprint)"
echo
echo "=== 续期后证书指纹 ==="
echo "  $AFTER"

if [ "$BEFORE" = "$AFTER" ]; then
  echo
  echo "证书未变化（可能未到续期窗口，属正常）。不 reload。"
  exit 0
fi

echo
echo "=== 证书已更新，校验新证书可读 ==="
# 校验的是**容器内**路径：nginx 读的是挂载进来的 /etc/nginx/ssl/...
if ! sudo docker exec campfire-web openssl x509 \
      -in "/etc/nginx/ssl/live/$DOMAIN/fullchain.pem" -noout -subject -enddate; then
  echo "错误：nginx 容器读不到新证书——不 reload，避免把站点打挂。" >&2
  echo "      请检查 $CRT_DIR 的挂载与权限。" >&2
  exit 1
fi

echo
echo "=== reload nginx（不中断连接）==="
sudo docker exec campfire-web nginx -t 2>&1 | tail -1
sudo docker exec campfire-web nginx -s reload
echo "完成。新证书生效。"
