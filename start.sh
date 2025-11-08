#!/bin/bash
set -e

echo "=========================================="
echo "EllenSings Bot with tun2socks"
echo "=========================================="

# Получаем SOCKS proxy из ENV (default для signbox на хосте)
SOCKS_PROXY="${SOCKS_PROXY:-socks5://host.docker.internal:2080}"

echo "Configuring TUN interface..."
# Настройка TUN-интерфейса
ip tuntap add dev tun0 mode tun
ip addr add 10.0.0.2/24 dev tun0
ip link set dev tun0 up

echo "Setting up routing..."
# Сохраняем оригинальный маршрут (для доступа к хосту)
ip route add 127.0.0.0/8 dev lo

# Заменяем маршрут по умолчанию на TUN
ip route del default || true
ip route add default dev tun0

echo "Starting tun2socks with proxy: $SOCKS_PROXY"
# Запускаем tun2socks с подробным логированием
./tun2socks -device tun0 -proxy "$SOCKS_PROXY" -loglevel debug &
TUN2SOCKS_PID=$!

# Проверяем что tun2socks запустился
sleep 3
if ! kill -0 $TUN2SOCKS_PID 2>/dev/null; then
    echo "ERROR: tun2socks failed to start"
    exit 1
fi

echo "tun2socks started successfully (PID: $TUN2SOCKS_PID)"
echo "All traffic (TCP+UDP) will go through proxy"
echo "=========================================="
echo "Starting Discord bot..."
echo ""

# Запуск бота
exec python -u bot.py
