#!/bin/sh
# Healthcheck шлюза: проверяем фактическую работоспособность маршрута
# через прокси, а не просто наличие процесса.
#
# 1. TUN-интерфейс поднят.
# 2. Локальный DNS-over-TLS resolver отвечает.
# 3. Discord API доступен по HTTPS через туннель.
set -eu

ip link show "${TUN_DEV:-tun0}" >/dev/null
getent hosts discord.com >/dev/null
curl -fsS --max-time 10 -o /dev/null "https://discord.com/api/v10/gateway"
