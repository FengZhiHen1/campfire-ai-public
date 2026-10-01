#!/usr/bin/env bash
# 用 Let's Encrypt 签发 campfire.wenran.me 的证书（HTTP-01 / webroot 方式）。
#
# ## 为什么用 HTTP-01 而不是 DNS-01
#
# DNS-01 需要把 Cloudflare Token 放到这台服务器上，而该 Token 对**整个 zone**
# 有 DNS 编辑权（同 zone 下还有另外 10 条记录属于其它项目）。为了一张证书把
# 全 zone 的写权限放到公网机器上，代价远大于收益。HTTP-01 只需要 80 端口可达。
#
# ## 为什么用 --webroot 而不是 --nginx
#
# certbot 的 nginx 插件会去改 nginx 配置（它不认识我们的 ssl.d 结构），
# 与我们「配置全部在仓库里、服务器只放证书」的分工冲突。webroot 只写一个文件，
# 由 nginx 的 `/.well-known/acme-challenge/` location 提供，互不干涉。
#
# ## 前置（脚本会检查）
#   - 域名 A 记录已指向本机公网 IP；
#   - 80 端口从公网可达；
#   - web 容器在跑，且 webroot 已挂载到 /var/www/certbot。
set -euo pipefail
cd /opt/campfire

DOMAIN="campfire.wenran.me"
# ⚠️ `:?` 的提示文案里**不能出现半角单引号**。
# bash 会把那个撇号当成引用开始，跨行一直吃到下一个撇号，
# 于是**后面若干行代码会被吞进这个变量**——症状是「明明写了的语句没执行」，
# 而报错位置离真正原因很远（实测：变量值变成了 `lwr0801430@163.com' || true)`，
# 紧随其后的 `resolved=` 整行消失，表现为「域名解析失败」）。
# 因此这里避开带撇号的写法（证书颁发机构的中文名即可，不必写英文原名）。
EMAIL="${ACME_EMAIL:?请用 ACME_EMAIL 提供一个邮箱，用于接收证书到期通知}"
WEBROOT_HOST="/opt/campfire/certbot-www"
CRT_DIR="/opt/campfire/infrastructure/nginx/ssl"
SSL_D_DIR="/opt/campfire/infrastructure/nginx/ssl.d"

echo "=== 前置检查 ==="
echo -n "  A 记录解析："
# 用 awk 一次做完「取第一行第一列」，**不要** `| head -1`：
# `set -o pipefail` 下，head 读够一行就退出会让上游 getent 收到 SIGPIPE（退出码 141），
# 整条管道因此判失败，命令替换拿到空串。而这是**竞态**——输出短时 getent 可能先写完
# 才被关闭，于是同一条命令时而成功时而失败（实测：交互式跑通过、脚本里跑失败）。
resolved="$(getent hosts "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || true)"
echo "${resolved:-（解析失败）}"
if [ "${resolved:-}" != "43.161.195.236" ]; then
  echo "  !! $DOMAIN 解析到 ${resolved:-无}，与本机 43.161.195.236 不符——HTTP-01 会失败" >&2
  exit 1
fi

echo -n "  webroot 可达（自测）："
mkdir -p "$WEBROOT_HOST/.well-known/acme-challenge"
echo "probe-$(date +%s)" > "$WEBROOT_HOST/.well-known/acme-challenge/probe"
probe_body="$(curl -s --max-time 10 "http://$DOMAIN/.well-known/acme-challenge/probe" || true)"
if [ -z "$probe_body" ]; then
  echo "空（nginx 未提供该路径）" >&2
  exit 1
fi
echo "ok（nginx 能读到 webroot）"
rm -f "$WEBROOT_HOST/.well-known/acme-challenge/probe"

echo
echo "=== 签发（certbot 容器）==="
# 用容器跑 certbot：服务器上没有 python/pip 环境，装系统包会污染主机；
# 容器方式用完即走，且与 compose 的其它服务隔离。
sudo docker run --rm \
  -v "$CRT_DIR:/etc/letsencrypt" \
  -v "$WEBROOT_HOST:/var/www/certbot" \
  certbot/certbot certonly \
    --webroot -w /var/www/certbot \
    -d "$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos --no-eff-email \
    --non-interactive \
    --keep-until-expiring

echo
echo "=== 生成 ssl.d 片段（443 的 server 块 + 80→443 跳转）==="
LEFTENCRYPT="$CRT_DIR/live/$DOMAIN"
# 用 `sudo test` 而不是 `test`：certbot 容器以 root 运行，签发出的目录是
# `drwx------ root root`，普通用户读不到——直接 `-f` 会误报「证书未找到」，
# 而证书其实好好的（实测踩到：签发明明成功，下一步却说找不到文件）。
if ! sudo test -f "$LEFTENCRYPT/fullchain.pem"; then
  echo "  证书未找到：$LEFTENCRYPT/fullchain.pem" >&2
  exit 1
fi
echo "  证书就位：$LEFTENCRYPT/fullchain.pem"

cat > "$SSL_D_DIR/campfire.conf" <<EOF
# 由 deploy 流程生成（certbot 签发成功后）。不要手工编辑——
# 重新签发/续期时本文件会被覆写。
#
# 内容：443 的 server 块（TLS 终止）与 80→443 跳转。
# 应用路由表经 include 复用 app-locations.conf，与 80 端口那份**完全一致**
# （避免「HTTPS 下某端点 404 而 HTTP 正常」这类因配置重复导致的漂移）。

server {
    listen       443 ssl;
    listen       [::]:443 ssl;
    http2        on;
    server_name  $DOMAIN;

    ssl_certificate      /etc/nginx/ssl/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key  /etc/nginx/ssl/live/$DOMAIN/privkey.pem;

    ssl_protocols        TLSv1.2 TLSv1.3;
    ssl_ciphers          HIGH:!aNULL:!MD5;
    ssl_session_cache    shared:SSL:10m;
    ssl_session_timeout  10m;

    # HSTS：证书确认可用后再开。先用一个较短的上界（1 天）而不是常见的 1 年——
    # 一旦域名将来需要回退到 HTTP，1 年的 HSTS 会让浏览器在有效期内拒绝明文访问，
    # 而且无法由服务端撤销。等稳定运行一段时间再考虑调长。
    add_header Strict-Transport-Security "max-age=86400" always;

    set \$campfire_api "api:8000";

    # ACME 挑战在 443 上也保留一份：部分 ACME 客户端会跟随后端返回的重定向来验证。
    location ^~ /.well-known/acme-challenge/ {
        root      /var/www/certbot;
        default_type "text/plain";
        access_log off;
    }

    include /etc/nginx/app-locations.conf;
}
EOF

# 80 → 443 跳转**不在这里生成**。
#
# 为什么（2026-10-01 真机踩到）：跳转该不该开，取决于一个**部署期事实**——
# 443 从公网是否真的可达。本机首次部署时 443 被云安全组拦着（80 通、443 超时，
# 服务器访问自己的公网 IP 也是同样结果，而 Docker 的 DNAT 规则与 80 完全对称）。
# 如果证书一签好就加跳转，站点会从「能用」直接变成「完全打不开」——而证书本身
# 完全正常，排查会先怀疑证书而不是安全组。
#
# 因此跳转由独立的、带可达性检查的步骤写入 redirect.d（见 scripts/tls-enable-redirect.sh）。
echo "  跳转未启用（443 可达性确认后再开，见 scripts/tls-enable-redirect.sh）"

echo "  已写入 $SSL_D_DIR/campfire.conf"
echo
echo "=== 校验 nginx 配置 ==="
sudo docker exec campfire-web nginx -t 2>&1 | tail -2

echo
echo "=== reload nginx（不中断连接）==="
sudo docker exec campfire-web nginx -s reload 2>&1 | tail -2
echo "完成"
