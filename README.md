# 🎵 EllenSings

Музыкальный Discord-бот в стиле **Ellen Joe** из Zenless Zone Zero.
Чистый, стабильный, с прозрачным прокси-шлюзом и красивым UI.

---

## ✨ Возможности

- 🎧 **Воспроизведение музыки** из YouTube и других источников (через yt-dlp)
- 🎛️ **Интерактивное управление** через кнопки и slash-команды
- 📃 **Очередь с пагинацией** — удобный просмотр и управление треками
- 🔁 **Режимы повтора**: трек, очередь, без повтора
- 🌐 **Прозрачный прокси-шлюз** (tun2socks + SOCKS5) с kill-switch
- 🎨 **Красивый UI** в стиле Ellen Joe
- 🐳 **Docker** — два контейнера, запуск одной командой
- 🔒 **Безопасность** — непривилегированный бот, kill-switch, pinned-зависимости, CI-проверки

---

## 🏗️ Архитектура

Проект разделён на **два контейнера**:

```
┌─────────────────────────────────────────────────────┐
│ Docker network (bot-net)                            │
│                                                     │
│  ┌───────────────────────────────────────────────┐  │
│  │ gateway (root, NET_ADMIN, /dev/net/tun)       │  │
│  │  tun2socks + iptables kill-switch             │  │
│  │  default route -> tun0 -> SOCKS5-прокси       │  │
│  │  весь прочий прямой egress ЗАБЛОКИРОВАН       │  │
│  │                                               │  │
│  │  ┌─────────────────────────────────────────┐  │  │
│  │  │ bot (non-root, cap_drop: ALL,           │  │  │
│  │  │      read_only, network_mode:           │  │  │
│  │  │      service:gateway)                   │  │  │
│  │  │  discord.py + yt-dlp + ffmpeg           │  │  │
│  │  └─────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
        SOCKS5-прокси (sing-box и т.п.)
        ОБЯЗАТЕЛЬНО с поддержкой UDP ASSOCIATE
```

- **gateway** — единственный контейнер с привилегиями (`NET_ADMIN`, `/dev/net/tun`).
  Собирает `tun2socks` **из исходников на закреплённой версии с проверкой SHA256**,
  поднимает TUN-интерфейс и включает **kill-switch**: iptables разрешает исходящий
  трафик только на адрес прокси, всё остальное мимо туннеля блокируется
  (включая IPv6 целиком).
- **bot** — живёт в network namespace шлюза (`network_mode: service:gateway`),
  поэтому физически не может ходить в сеть мимо туннеля. Запускается от
  непривилегированного пользователя, с `cap_drop: [ALL]`, `no-new-privileges`
  и `read_only` файловой системой (запись только в tmpfs `/tmp`).
- **Healthcheck'и проверяют работу, а не «наличие процесса»**: шлюз делает
  HTTPS-запрос к Discord API через туннель (DNS при этом идёт по UDP —
  заодно проверяется UDP ASSOCIATE), бот проверяет свежесть heartbeat-файла,
  который обновляется только пока WebSocket-соединение с Discord живо.

---

## 🚀 Быстрый старт

### 1. Предварительные требования

- **Docker** и **Docker Compose** (Linux-хост; нужен модуль `tun` — обычно уже загружен, иначе `sudo modprobe tun`)
- **SOCKS5-прокси с поддержкой UDP ASSOCIATE** (например, socks-inbound в sing-box),
  доступный из Docker-сети (слушает `0.0.0.0` или IP docker-бриджа)

### 2. Настройка

```bash
git clone <repo-url>
cd EllenSingsV2
cp .env.example .env
# отредактируй .env: DISCORD_TOKEN и PROXY_URL
```

### 3. Запуск

```bash
docker compose up -d --build
docker compose logs -f        # логи
docker compose ps             # статус + health
docker compose down           # остановка
```

Бот стартует только после того, как healthcheck шлюза подтвердит, что туннель
реально работает. Если прокси не поддерживает UDP ASSOCIATE — шлюз останется
`unhealthy`, и это будет видно сразу, а не в виде «голос молчит».

---

## 🔐 Discord-приложение: токен и права

### Токен

- Для **production используй отдельное приложение/токен** — не тот, с которым разрабатываешь.
- **Утечка = немедленный перевыпуск** (Developer Portal → Bot → Reset Token).
- Токен передаётся через `.env` (не коммитится) или Docker secrets —
  бот поддерживает `DISCORD_TOKEN_FILE` с путём к файлу с токеном.

### Права (permissions)

Боту **не нужен Administrator**. Достаточно:

| Право | Зачем |
|---|---|
| View Channels | видеть каналы |
| Send Messages | сообщения и панель управления |
| Embed Links | embed'ы |
| Read Message History | редактирование своих сообщений |
| Connect | подключение к голосовому каналу |
| Speak | воспроизведение |

Ссылка-приглашение с этим минимальным набором (permissions=3230720):

```
https://discord.com/api/oauth2/authorize?client_id=ВАШ_CLIENT_ID&permissions=3230720&scope=bot%20applications.commands
```

В Developer Portal включи **Message Content Intent** (используется префикс-командами `!reload`).

### Кто может управлять ботом

Команды управления (`/skip`, `/stop`, `/pause`, `/resume`, `/clear`, `/repeat`)
и кнопки панели доступны **только участникам того же голосового канала**, где
находится бот. `!reload` — только владельцу бота.

---

## 🌐 Прокси и kill-switch

- `PROXY_URL` задаётся в `.env`: `socks5://host:port` или `socks5://user:pass@host:port`.
  Прокси на хосте доступен из контейнера как `host.docker.internal`.
- **UDP ASSOCIATE обязателен** — Discord Voice работает по UDP.
- Kill-switch в шлюзе: `OUTPUT DROP` по умолчанию; разрешены только loopback,
  TUN-интерфейс и адрес прокси. DNS уходит на публичный резолвер **через туннель**
  (без утечки DNS через хост). IPv6 отключён и заблокирован.
- URL прокси с логином/паролем **не пишется в логи** (логируется только host:port),
  а tun2socks получает его через конфиг-файл, а не argv.

---

## 📋 Команды бота

Полный список — в [COMMANDS.md](COMMANDS.md).

| Команда | Описание |
|---------|----------|
| `/play <запрос>` | Добавить трек (URL или поиск) |
| `/search <запрос>` | Поиск с интерактивным выбором |
| `/playlist <URL>` | Загрузить плейлист (до 50 треков) |
| `/skip` / `/stop` / `/pause` / `/resume` | Управление воспроизведением |
| `/queue` / `/clear` | Очередь |
| `/repeat [mode]` | Режим повтора |
| `/nowplaying` | Панель управления |
| `/ping` | Задержка бота |

---

## 🛠️ Структура проекта

```
EllenSingsV2/
├── bot.py                  # Точка входа: сигналы, heartbeat, обработка ошибок
├── healthcheck.py          # Healthcheck контейнера бота
├── cogs/
│   └── music.py            # Музыкальный модуль (команды, очередь, UI, права)
├── utils/
│   └── ytdl.py             # Обёртка yt-dlp (TLS включён, валидация URL)
├── gateway/
│   ├── Dockerfile          # Сборка tun2socks из исходников (pinned + SHA256)
│   ├── entrypoint.sh       # TUN, маршруты, kill-switch, сигналы
│   └── healthcheck.sh      # Проверка туннеля (TCP+UDP через прокси)
├── Dockerfile              # Multi-stage образ бота (non-root)
├── compose.yml             # Два сервиса + hardening + лимиты ресурсов
├── requirements.txt        # Pinned-зависимости (проверяются pip-audit)
└── .github/workflows/
    ├── ci.yml              # ruff, bandit, pip-audit, hadolint, trivy
    └── docker-publish.yml  # Сборка и публикация обоих образов
```

---

## 🔧 Разработка

- **Линтеры/сканеры локально**:
  ```bash
  pip install ruff "bandit[toml]" pip-audit
  ruff check .
  bandit -c pyproject.toml -ll -r bot.py healthcheck.py cogs utils
  pip-audit -r requirements.txt --ignore-vuln PYSEC-2026-3002
  ```
- **Обновление зависимостей**: меняй пины в `requirements.txt` осознанно,
  CI прогонит pip-audit.
- **Обновление tun2socks**: поменяй `TUN2SOCKS_VERSION` и `TUN2SOCKS_SHA256`
  в `gateway/Dockerfile` (инструкция по пересчёту хеша — там же).
- `!reload` (только владелец) перезагружает cog'и без рестарта.

---

## 🐛 Известные проблемы и решения

### Шлюз unhealthy
- Проверь, что прокси доступен из Docker-сети и поддерживает **UDP ASSOCIATE**.
- `docker compose logs gateway` — kill-switch и tun2socks пишут диагностику.

### Бот не подключается к голосовому каналу
- Убедись, что у бота есть права **Connect** и **Speak** в этом канале.
- Проверь health шлюза: `docker compose ps`.

### Ошибки при загрузке треков
- **"Video unavailable"** — видео удалено или недоступно.
- **"Требуется вход в аккаунт"** — контент требует авторизации, бот его не играет.
- Регион-блок обходится корректной настройкой прокси.

---

## 📝 Лицензия

MIT License — используйте свободно!
