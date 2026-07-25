# 🚀 Быстрый старт EllenSings

## 0️⃣ Что нужно заранее

- Linux-хост с Docker и Docker Compose
- **SOCKS5-прокси с поддержкой UDP ASSOCIATE** (например, sing-box socks-inbound),
  слушающий на адресе, доступном из Docker-сети
- Discord-токен (для production — отдельный от dev!)

## 1️⃣ Настройка (1 минута)

```bash
cp .env.example .env
nano .env   # DISCORD_TOKEN и PROXY_URL
```

```env
DISCORD_TOKEN=токен_с_discord_developers
PROXY_URL=socks5://host.docker.internal:2080
```

## 2️⃣ Запуск

```bash
docker compose up -d --build
```

Поднимутся два контейнера:
- `ellensings-gateway` — туннель tun2socks + kill-switch (весь трафик только через прокси)
- `ellensings-bot` — сам бот (стартует после того, как туннель прошёл healthcheck)

## 3️⃣ Проверка

```bash
docker compose ps        # оба контейнера должны стать healthy
docker compose logs -f   # логи
```

Если `gateway` остаётся unhealthy — прокси недоступен из Docker-сети
или не поддерживает UDP ASSOCIATE.

## 4️⃣ Приглашение бота

Минимальные права, без Administrator:

```
https://discord.com/api/oauth2/authorize?client_id=ВАШ_CLIENT_ID&permissions=3230720&scope=bot%20applications.commands
```

## 📋 Основные команды бота

- `/play <запрос>` — добавить трек
- `/search <запрос>` — поиск с выбором
- `/skip`, `/stop`, `/pause`, `/resume` — управление (только из voice-канала бота)
- `/queue` — очередь
- `/nowplaying` — панель управления с кнопками

## 🛑 Остановка

```bash
docker compose down
```

---

**Всё!** Бот готов к работе 🎵
