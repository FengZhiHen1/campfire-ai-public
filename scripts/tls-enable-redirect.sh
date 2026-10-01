#!/usr/bin/env bash
# 在**确认 443 从公网真的可达之后**启用 80→443 跳转。
#
# 为什么要有这一步而不是直接写进 nginx.conf（2026-10-01 真机踩到）：
#   本机首次部署时 443 被云安全组拦着——80 通、443 超时，而服务器访问**自己的
#   公网 IP** 也是同样结果，Docker 的 DNAT 规则对 80/443 完全对称、本机 iptables
#   也没有任何针对 443 的 DROP。因此那是云侧安全组，不是配置问题。
#   在这种状态下若无条件跳转，站点会从「能用」变成「完全打不开」，而证书完全正常，
#   排查方向会跑偏。
#
# 判据（三条全过才启用）：
#   1. 443 端口能建立 TCP 连接；
#   2. 能完成 TLS 握手并拿到证书；
#   3. HTTPS 上 `/readyz` 返回 200。
# 只做一条（例如只看端口通）是不够的：端口通但证书链不对时，跳转同样会把用户送进
# 浏览器警告页，那比留在 HTTP 更糟。
set -euo pipefail
cd /opt/campfire

DOMAIN="campfire.wenran.me"
REDIRECT_DIR="/opt/campfire/infrastructure/nginx/redirect.d"
ENV_FILE="/opt/campfire/.env.prod"

echo "=== 前置：443 可达性三连检 ==="

echo -n "  1. TCP 443 可连："
if ! timeout 8 bash -c "cat < /dev/null > /dev/tcp/$DOMAIN/443" 2>/dev/null; then
  echo "否"
  echo
  echo "  !! $DOMAIN:443 无法建立 TCP 连接。请先在云控制台的安全组里放行 443/tcp。" >&2
  echo "     本机已知事实：80 通、443 超时，且这是云侧（安全组）而非本机 iptables——" >&2
  echo "     Docker DNAT 对两个端口是对称的，本机也没有 443 的 DROP 规则。" >&2
  echo "     未启用跳转（保持站点可用）。" >&2
  exit 1
fi
echo "是"

echo -n "  2. TLS 握手与证书："
if ! echo | timeout 12 openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null \
     | grep -q "Verify return code: 0"; then
  echo "失败（证书链未通过校验）"
  echo "  !! 未启用跳转：端口虽通但证书未通过校验，跳转会把用户送进浏览器警告页。" >&2
  exit 1
fi
echo "通过（链校验 code 0）"

echo -n "  3. HTTPS /readyz："
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/readyz" || echo 000)"
if [ "$code" != "200" ]; then
  echo "HTTP $code"
  echo "  !! 未启用跳转：HTTPS 上的就绪探针不是 200，说明应用在 HTTPS 下未就绪。" >&2
  exit 1
fi
echo "HTTP 200"

echo
echo "=== 三条全过 → 启用跳转 ==="
mkdir -p "$REDIRECT_DIR"
cat > "$REDIRECT_DIR/redirect.conf" <<'EOF'
# 由部署流程在 443 可达性三重校验通过后生成。
# 内容：把 80 上的非 ACME 流量跳到 HTTPS。
#
# ACME 挑战必须豁免且**必须优先于 redirect**：否则证书续期时，验证请求会被
# 301 到 HTTPS，而某些 ACME 客户端不跟随跨协议的跳转，续期会静默失败——
# 等到证书过期才发现。
location ^~ /.well-known/acme-challenge/ {
    root      /var/www/certbot;
    default_type "text/plain";
    access_log off;
}

location / {
    return 301 https://$host$request_uri;
}
EOF

echo "  已写入 $REDIRECT_DIR/redirect.conf"
echo
echo "=== 校验并 reload ==="
if ! sudo docker exec campfire-web nginx -t 2>&1 | tail -1; then
  echo "  !! nginx 配置校验失败，回滚跳转文件以免影响线上" >&2
  rm -f "$REDIRECT_DIR/redirect.conf"
  exit 1
fi
sudo docker exec campfire-web nginx -s reload
echo "  已 reload"

echo
echo "=== 验证跳转生效 ==="
printf "  http://%s/   -> " "$DOMAIN"
curl -s -o /dev/null -w '%{http_code}（301 = 已跳转）\n' --max-time 10 "http://$DOMAIN/"
printf "  ACME 路径豁免 -> "
curl -s -o /dev/null -w '%{http_code}（404 = 未被跳转，正确）\n' --max-time 10 \
  "http://$DOMAIN/.well-known/acme-challenge/nonexistent"
