#!/bin/bash

# Настройка TUN-интерфейса
ip tuntap add dev tun0 mode tun
ip addr add 10.0.0.2/24 dev tun0
ip link set dev tun0 up

# Заменяем маршрут по умолчанию
ip route add default dev tun0

# Запускаем tun2socks, подключаемся к Nekoray на хосте по IP
tun2socks -device tun0 -proxy socks5://172.17.0.1:2080 &

# Пауза для инициализации tun2socks
sleep 2

# Запуск бота
python bot.py
