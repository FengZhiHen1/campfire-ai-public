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
#
# 必须是**完整的独立 server 块**，不能只写 `location /`（2026-10-01 真机踩到）：
# 80 的 server 块已经 `include app-locations.conf`，而那里有 SPA 的 `location /`。
# nginx 不允许同一 server 内重复 location，实测直接拒绝启动：
#     [emerg] duplicate location "/" in /etc/nginx/app-locations.conf:107
# 独立 server 块改按 server_name 精确匹配取胜，且能保留「用 IP 直连仍可排障」。
cat > "$REDIRECT_DIR/redirect.conf" <<'EOF'
# 由 scripts/tls-enable-redirect.sh 在 443 可达性三重校验通过后生成。
#
# 为什么是独立 server 块而不是往 80 的块里加 `location /`：
# 那个块已经 include app-locations.conf（含 SPA 的 `location /`），
# 同一 server 内重复 location 会让 nginx 拒绝启动
# （实测 [emerg] duplicate location "/" ...app-locations.conf）。
# 独立块靠 server_name 精确匹配优先于 `_` 兜底块，因此只影响真实域名，
# 用 IP 直连（运维排障）仍走原来那个块。
server {
    listen       80;
    listen       [::]:80;
    server_name  campfire.wenran.me;

    # ACME 挑战必须豁免且**必须优先于 redirect**：否则证书续期时验证请求会被 301
    # 到 HTTPS，而某些 ACME 客户端不跟随跨协议跳转，续期会静默失败——
    # 等到证书过期才发现。用 `^~` 确保优先于正则 location。
    location ^~ /.well-known/acme-challenge/ {
        root      /var/www/certbot;
        default_type "text/plain";
        access_log off;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}
EOF

echo "  已写入 $REDIRECT_DIR/redirect.conf"
echo
echo "=== 校验并 reload ==="
if ! sudo docker exec campfire-web nginx -t 2>&1 | tail -1; then
  echo "  !! nginx 配置校验失败，回滚跳转文件以免影响线上（error 见上）" >&2
  rm -f "$REDIRECT_DIR/redirect.conf"
  exit 1
fi
sudo docker exec campfire-web nginx -s reload
echo "  已 reload"

echo
echo "=== 验证（五项，全看才说明真的切过去了）==="
#
# 关于 curl 的跳转行为（2026-10-01 实测，纠正我先前的错误理解）：
#   curl **默认不跟随**重定向，`%{http_code}` 就是第一跳的状态码。
#   我先前以为它默认跟随、并据此加了 `--max-redirs 0`——那是错的，而且
#   `--max-redirs 0` 会让下面那条「跟随跳转」的检查直接失败（它禁止了唯一的跳转）。
#   要跟随必须显式 `-L`。判据用 `%{num_redirects}` 区分：0 = 没跟随，≥1 = 跟随过。
printf "  http://%s/          -> " "$DOMAIN"
curl -s -o /dev/null -w '%{http_code}（301 = 已跳转）\n' --max-time 10 "http://$DOMAIN/"
printf "  ACME 路径豁免        -> "
curl -s -o /dev/null -w '%{http_code}（404 = 未被跳转，正确）\n' --max-time 10 \
  "http://$DOMAIN/.well-known/acme-challenge/nonexistent"
printf "  https://%s/readyz   -> " "$DOMAIN"
curl -s -o /dev/null -w '%{http_code}（200 = HTTPS 上的应用就绪）\n' --max-time 15 "https://$DOMAIN/readyz"
printf "  跟随跳转后的最终页    -> "
# 这一条是「用户实际体验」：显式 -L 跟随 301 后，应拿到 HTTPS 上的 SPA（200 + https）。
curl -sL -o /dev/null -w '%{http_code} @ %{url_effective}（跟随 %{num_redirects} 跳）\n' \
  --max-time 20 "http://$DOMAIN/"
printf "  配置三项已是 https   -> "
# 这一步查的是上面 4a 有没有真的落到文件里。
#
# 为什么不在这里直接验证「cookie 带 Secure」（2026-10-01 踩到）：那需要一次**成功的**
# 登录，而脚本不该持有真实账号凭据；我先前用不存在的账号探测，signin 必然失败、
# 自然拿不到 Set-Cookie，于是恒报「无」——**一个永远失败的检查比没有检查更糟**，
# 因为它会让人以为配置没生效。
#
# 改为直接判据：Secure 属性由 SuperTokens 按其 api_domain 推导，因此**这三个值就是
# 决定因素**，检查它们既确定又无需凭据。
#
# 真实的 cookie 属性验证（需要凭据）放在验收流程里，那里会用真账号登录并读
# `Set-Cookie` 原文（注意不能用 urllib：它合并多个 Set-Cookie，会误报 HttpOnly=False）。
non_https="$(grep -E '^(SUPERTOKENS_API_DOMAIN|SUPERTOKENS_WEBSITE_DOMAIN|PUBLIC_BASE_URL)=' "$ENV_FILE" \
  | grep -v '=https://' || true)"
if [ -z "$non_https" ]; then
  echo "是"
else
  echo "否 —— 以下项仍是 http，Secure 属性不会生效："
  printf '%s\n' "$non_https" | sed 's/^/      /'
fi
