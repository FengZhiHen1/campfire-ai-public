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
echo "=== 三条全过 → 启用 HTTPS ==="
echo
echo "--- 4a. 先把后端的域名配置切到 https ---"
#
# 为什么这一步不能漏（2026-10-01 自查发现）：启用 HTTPS 需要**三处**一起改，
# 只改 nginx 会留下一个不易察觉的不一致——
#
#   SUPERTOKENS_API_DOMAIN / SUPERTOKENS_WEBSITE_DOMAIN 决定身份服务如何推导
#   cookie 域与 `Secure` 属性、以及重定向地址的白名单。若页面已是 https 而这两个值
#   仍是 http，会话 cookie 可能不带 `Secure`（安全降级），重定向白名单也会与实际
#   访问地址不符。它不会立刻报错——登录可能仍然可用——因此属于「静默不安全」。
#
# 顺序：先切配置、再切跳转。反过来的话，跳转先生效而配置仍是 http，
# 中间会有一小段「HTTPS 页面 + http 配置」的组合。
if [ ! -f "$ENV_FILE" ]; then
  echo "  !! 找不到 $ENV_FILE，无法切换域名配置。" >&2
  exit 1
fi
cp "$ENV_FILE" "$ENV_FILE.before-https"
echo "  已备份配置到 $ENV_FILE.before-https"

for key in SUPERTOKENS_API_DOMAIN SUPERTOKENS_WEBSITE_DOMAIN PUBLIC_BASE_URL; do
  current="$(grep -E "^$key=" "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
  if [ -z "$current" ]; then
    echo "  !! $ENV_FILE 里没有 $key，跳过（请人工确认这一项）" >&2
    continue
  fi
  # 只把 http:// 换成 https://，不碰主机名——换域名是另一件事，不该由本脚本顺手做。
  updated="$(printf '%s' "$current" | sed 's|^http://|https://|')"
  if [ "$current" = "$updated" ]; then
    echo "  $key 已是 https（$current）"
  else
    sed -i "s|^$key=.*|$key=$updated|" "$ENV_FILE"
    echo "  $key: $current -> $updated"
  fi
done

echo
echo "  让 api 重新读取配置…"
sudo docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE" up -d --no-build api 2>&1 | tail -2

echo
echo "--- 4b. 写入 80 -> 443 跳转 ---"
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
echo "=== 验证（四项，全看才说明真的切过去了）==="
printf "  http://%s/          -> " "$DOMAIN"
curl -s -o /dev/null -w '%{http_code}（301 = 已跳转）\n' --max-time 10 "http://$DOMAIN/"
printf "  ACME 路径豁免        -> "
curl -s -o /dev/null -w '%{http_code}（404 = 未被跳转，正确）\n' --max-time 10 \
  "http://$DOMAIN/.well-known/acme-challenge/nonexistent"
printf "  https://%s/readyz   -> " "$DOMAIN"
curl -s -o /dev/null -w '%{http_code}（200 = HTTPS 上的应用就绪）\n' --max-time 15 "https://$DOMAIN/readyz"
printf "  会话 cookie 带 Secure -> "
# 这一步查的是上面 4a 有没有真的生效。判据：登录响应里的会话 cookie 必须带 `Secure`；
# 缺了它，浏览器在 HTTPS 下仍可能用明文回传凭据（安全降级），而且不会报错。
# 这里只回报告"有/无"，不复述 cookie 值。
secure="$(curl -s -D - -o /dev/null --max-time 15 -X POST "https://$DOMAIN/api/auth/signin" \
  -H 'Content-Type: application/json' -H 'rid: emailpassword' \
  --data '{"formFields":[{"id":"email","value":"__probe_nonexistent__"},{"id":"password","value":"x"}]}' \
  | grep -i '^set-cookie:.*sAccessToken' | grep -ci 'secure' || true)"
if [ "${secure:-0}" -ge 1 ]; then
  echo "有（配置切换已生效）"
else
  echo "无 —— 请人工确认：登录一个真实账号再看，或检查 SUPERTOKENS_*_DOMAIN"
fi
