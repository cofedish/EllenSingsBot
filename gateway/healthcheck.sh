#!/bin/sh
# Healthcheck шлюза: проверяем фактическую работоспособность маршрута
# через прокси, а не просто наличие процесса.
#
# 1. TUN-интерфейс поднят.
# 2. HTTPS-запрос к Discord API проходит через туннель.
#    DNS-запрос при этом идёт по UDP через tun0 -> SOCKS5 UDP ASSOCIATE,
#    так что заодно проверяется и поддержка UDP у прокси.
set -eu

ip link show "${TUN_DEV:-tun0}" >/dev/null
curl -fsS --max-time 10 -o /dev/null "https://discord.com/api/v10/gateway"
