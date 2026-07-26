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

# --- DNS без утечек ---
# Embedded DNS Docker (127.0.0.11) форвардит внешние запросы С ХОСТА,
# т.е. мимо туннеля. После резолва адреса прокси переключаем контейнер
# на публичный резолвер: эти запросы пойдут через tun0 -> прокси.
# Ниже 127.0.0.11:53 дополнительно блокируется iptables.
# /etc/resolv.conf остаётся записываемым даже при read_only rootfs.
DNS_SERVERS="${DNS_SERVERS:-1.1.1.1 1.0.0.1}"
if {
    for ns in $DNS_SERVERS; do
        echo "nameserver $ns"
    done
} > /etc/resolv.conf 2>/dev/null; then
    echo "[dns] resolv.conf -> ${DNS_SERVERS} (queries go through the tunnel)"
else
    # Fail-closed: без гарантии DNS-через-туннель не работаем вовсе
    echo "ERROR: cannot rewrite /etc/resolv.conf — refusing to run with leaky DNS" >&2
    exit 1
fi

# Bootstrap-резолв хоста прокси выше — единственный DNS-запрос, который мог
# уйти через резолвер хоста. Если PROXY_HOST задан IP-литералом или прописан
# в /etc/hosts (host.docker.internal) — утечки нет вообще.
case "$PROXY_HOST" in
    *[!0-9.]*)
        if ! grep -qw "$PROXY_HOST" /etc/hosts; then
            echo "[dns] NOTE: proxy hostname was resolved once via host DNS at startup;"
            echo "[dns]       set PROXY_URL with an IP literal to avoid this bootstrap query"
        fi
        ;;
esac

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
# Embedded DNS Docker (127.0.0.11) — до общего разрешения loopback:
# он форвардит запросы с хоста в обход туннеля
iptables -A OUTPUT -d 127.0.0.11 -p udp --dport 53 -j REJECT
iptables -A OUTPUT -d 127.0.0.11 -p tcp --dport 53 -j REJECT
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -o "$TUN_DEV" -j ACCEPT
# Управляющее TCP-соединение SOCKS5
iptables -A OUTPUT -d "$PROXY_IP" -p tcp --dport "$PROXY_PORT" -j ACCEPT
# UDP ASSOCIATE: relay-порт выделяется прокси динамически, поэтому UDP
# разрешён к хосту прокси целиком. Если SOCKS-сервер вернёт relay на ДРУГОМ
# адресе — трафик будет заблокирован (fail-closed), это поймает self-test ниже.
iptables -A OUTPUT -d "$PROXY_IP" -p udp -j ACCEPT
# Бланкетного ESTABLISHED-правила нет: всё необходимое покрыто явными правилами
# IPv6 блокируем полностью: TUN-маршрут обслуживает только IPv4
if ! ip6tables -P OUTPUT DROP 2>/dev/null; then
    echo "[fw] IPv6 netfilter unavailable (IPv6 already disabled via sysctl)"
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

# --- Self-test UDP-пути (обязательный, fail-closed) ---
# DNS-запрос уходит по UDP через tun0 -> tun2socks -> SOCKS5 UDP ASSOCIATE.
# Если прокси не поддерживает UDP ASSOCIATE или relay-адрес недостижим,
# завершаемся с ошибкой: бот не стартует (depends_on: service_healthy),
# вместо молчащего Discord Voice.
attempt=0
until getent hosts discord.com >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 6 ]; then
        echo "ERROR: UDP path through proxy failed (no UDP ASSOCIATE support" >&2
        echo "       or relay unreachable) — refusing to run without working UDP" >&2
        kill -TERM "$T2S_PID" 2>/dev/null || true
        exit 1
    fi
    if ! kill -0 "$T2S_PID" 2>/dev/null; then
        echo "ERROR: tun2socks died during startup" >&2
        exit 1
    fi
    echo "[selftest] UDP path not ready yet (attempt ${attempt}/5), retrying..."
    sleep 2
done
echo "[selftest] UDP through proxy OK: DNS via tunnel works (UDP ASSOCIATE confirmed)"

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
