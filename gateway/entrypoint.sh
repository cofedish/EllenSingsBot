#!/bin/sh
# ============================================================
# Gateway: TUN-интерфейс + tun2socks + iptables kill-switch
#
# Весь трафик контейнеров, живущих в этом network namespace
# (сам gateway и бот через network_mode: service:gateway),
# уходит в tun0 -> tun2socks -> SOCKS5-прокси.
# Прямой исходящий трафик мимо прокси блокируется iptables.
#
# ВАЖНО: SOCKS5-прокси должен поддерживать UDP ASSOCIATE,
# иначе Discord Voice (UDP) работать не будет.
# ============================================================
set -eu

TUN_DEV="${TUN_DEV:-tun0}"
TUN_ADDR="${TUN_ADDR:-10.0.0.2/24}"

if [ -z "${PROXY_URL:-}" ]; then
    echo "ERROR: PROXY_URL is not set (e.g. socks5://user:pass@host:2080)" >&2
    exit 1
fi

# --- Парсим PROXY_URL; логин/пароль НЕ логируем ---
SCHEME=$(printf '%s' "$PROXY_URL" | sed -E 's|^([a-zA-Z0-9+.-]+)://.*$|\1|')
HOSTPORT=$(printf '%s' "$PROXY_URL" | sed -E 's|^[a-zA-Z0-9+.-]+://([^@]*@)?([^/]+)/?.*$|\2|')
CREDS=$(printf '%s' "$PROXY_URL" | sed -nE 's|^[a-zA-Z0-9+.-]+://([^@/]+)@.*$|\1|p')
PROXY_HOST="${HOSTPORT%%:*}"
PROXY_PORT="${HOSTPORT##*:}"
case "$PROXY_PORT" in
    ''|*[!0-9]*) PROXY_PORT=1080 ;;
esac

echo "[proxy] scheme=${SCHEME} endpoint=${PROXY_HOST}:${PROXY_PORT} (credentials redacted)"

# --- Резолвим хост прокси ДО перестройки маршрутов ---
PROXY_IP=$(getent hosts "$PROXY_HOST" | awk '{print $1; exit}')
if [ -z "$PROXY_IP" ]; then
    echo "ERROR: cannot resolve proxy host '${PROXY_HOST}'" >&2
    exit 1
fi
echo "[net] proxy ip: ${PROXY_IP}"

# /etc/resolv.conf монтируется read-only из gateway/resolv.conf одновременно
# в gateway и bot. Публичные DNS-адреса маршрутизируются через tun0, поэтому
# Docker embedded DNS (127.0.0.11), форвардящий запросы с хоста, не используется.
echo "[dns] static resolv.conf active (queries go through the tunnel)"

GATEWAY_IP=$(ip -4 route show default | awk '{print $3; exit}')
if [ -z "$GATEWAY_IP" ]; then
    echo "ERROR: no default gateway found" >&2
    exit 1
fi

# --- TUN-интерфейс ---
ip tuntap add dev "$TUN_DEV" mode tun 2>/dev/null || true
ip addr replace "$TUN_ADDR" dev "$TUN_DEV"
ip link set dev "$TUN_DEV" up

# Маршрут до прокси через оригинальный шлюз — иначе после смены
# default route tun2socks сам не достучится до SOCKS-сервера
ip route replace "${PROXY_IP}/32" via "$GATEWAY_IP"

# Весь остальной трафик — в TUN
ip route replace default dev "$TUN_DEV"
echo "[net] default route -> ${TUN_DEV}; ${PROXY_IP}/32 -> via ${GATEWAY_IP}"

# --- Kill-switch: разрешены только loopback, TUN и сам прокси ---
iptables -F OUTPUT
iptables -P OUTPUT DROP
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -o "$TUN_DEV" -j ACCEPT
# Управляющее TCP-соединение SOCKS5
iptables -A OUTPUT -d "$PROXY_IP" -p tcp --dport "$PROXY_PORT" -j ACCEPT
# UDP ASSOCIATE: relay-порт выделяется прокси динамически,
# поэтому разрешаем UDP к хосту прокси целиком
iptables -A OUTPUT -d "$PROXY_IP" -p udp -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
# IPv6 блокируем полностью: TUN-маршрут обслуживает только IPv4
if command -v ip6tables >/dev/null 2>&1; then
    ip6tables -P OUTPUT DROP 2>/dev/null || true
fi
echo "[fw] kill-switch active: direct egress allowed only to ${PROXY_IP}"

# --- Конфиг tun2socks пишем в файл (креды не светятся в argv/ps) ---
# Прокси передаём по IP: DNS-запрос самого tun2socks не должен идти в туннель
if [ -n "$CREDS" ]; then
    T2S_PROXY="${SCHEME}://${CREDS}@${PROXY_IP}:${PROXY_PORT}"
else
    T2S_PROXY="${SCHEME}://${PROXY_IP}:${PROXY_PORT}"
fi

CONF=/run/tun2socks.yml
umask 077
cat > "$CONF" <<EOF
device: ${TUN_DEV}
proxy: ${T2S_PROXY}
loglevel: ${T2S_LOGLEVEL:-warning}
EOF

echo "[tun2socks] starting..."
tun2socks --config "$CONF" &
T2S_PID=$!

echo "[dns] starting local DNS-over-TLS resolver..."
unbound -d -c /etc/unbound/ellensings.conf &
DNS_PID=$!

shutdown() {
    echo "[gateway] signal received, stopping resolver and tun2socks"
    kill -TERM "$DNS_PID" 2>/dev/null || true
    kill -TERM "$T2S_PID" 2>/dev/null || true
}
trap shutdown TERM INT

# Первый wait может прерваться сигналом; дожидаемся фактического выхода процесса
set +e
wait "$T2S_PID"
EXIT_CODE=$?
while kill -0 "$T2S_PID" 2>/dev/null; do
    wait "$T2S_PID"
    EXIT_CODE=$?
done

echo "[gateway] tun2socks exited with code ${EXIT_CODE}"
exit "$EXIT_CODE"
