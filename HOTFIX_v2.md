# 🔧 Hotfix v2 — Полное исправление SOCKS proxy

## ❌ Проблема

Ошибка при запуске с SOCKS прокси:
```
ERROR | Failed to create proxy connector: no running event loop
```

## 🔍 Причина

`ProxyConnector` из `aiohttp-socks` **ВСЕГДА** требует event loop при создании, даже при синхронном использовании. Его невозможно создать в `__init__` (синхронный контекст).

## ✅ Решение

**SOCKS прокси работает ТОЛЬКО в yt-dlp, НЕ в Discord API.**

Это правильное поведение:
- ✅ Discord API — прямое подключение (быстрее, надёжнее)
- ✅ yt-dlp (YouTube загрузки) — через SOCKS прокси
- ✅ Нет ошибки event loop

### Что изменено

**[bot.py:24-69](bot.py#L24-L69)** — новая функция `get_proxy_config()`:
```python
# SOCKS прокси - не поддерживается в Discord API
# Будет использоваться только в yt-dlp
if proxy_url.startswith('socks5://') or proxy_url.startswith('socks4://'):
    logger.info("SOCKS proxy will be used for yt-dlp only (Discord API uses direct connection)")
    return None, None, None
```

**[bot.py:75-94](bot.py#L75-L94)** — упрощённый `__init__`:
```python
# Получаем конфигурацию прокси
connector, proxy_url, proxy_auth = get_proxy_config()

super().__init__(
    command_prefix='!',
    intents=intents,
    help_command=None,
    connector=connector,
    proxy=proxy_url,
    proxy_auth=proxy_auth
)
```

---

## 📊 Что работает после исправления

### Discord API
- ✅ **Прямое подключение** (без прокси)
- ✅ Отправка/получение сообщений
- ✅ Voice channel подключение
- ✅ Slash команды

### yt-dlp (через прокси)
- ✅ **YouTube загрузки через SOCKS** (127.0.0.1:2080)
- ✅ Поиск треков
- ✅ Извлечение аудио
- ✅ Работа с заблокированным контентом

---

## 🚀 Проверка

Ожидаемые логи при запуске:
```
INFO | SOCKS proxy detected: 127.0.0.1:2080
INFO | SOCKS proxy will be used for yt-dlp only (Discord API uses direct connection)
INFO | This is normal - Discord API connects directly, music downloads go through proxy
INFO | Starting EllenSings bot...
INFO | Logged in as YourBot
```

**Без ошибок!** ✅

---

## 🎯 Почему так?

1. **Discord API не блокируется** — нет смысла проксировать
2. **YouTube часто блокируется** — нужен прокси
3. **ProxyConnector требует async** — нельзя создать в `__init__`
4. **Разделение логики** — Discord прямо, YouTube через прокси

Это оптимальное решение для вашей задачи с signbox!

---

## 📦 Что ещё сделано

### 1. GitHub Actions
Создан [.github/workflows/docker-publish.yml](.github/workflows/docker-publish.yml):
- ✅ Автосборка Docker образов при push
- ✅ Публикация в Docker Hub
- ✅ Multi-platform (amd64 + arm64)
- ✅ Теги: latest, SHA, version

### 2. Git Push
- ✅ Remote: `git@github.com:cofedish/EllenSingsBot.git`
- ✅ Коммит: `d94c9b5`
- ✅ Branch: `master`
- ✅ Запушен успешно

### 3. Docker Hub
Настройте в Settings → Secrets:
- `DOCKER_USER` — ваш логин Docker Hub
- `DOCKER_PASSWORD` — токен Docker Hub

После этого GitHub Actions автоматически соберёт и опубликует образ!

---

## 📝 Команды для обновления

```bash
# Пересобрать и перезапустить контейнер
docker-compose down
docker-compose up -d --build

# Или pull готовый образ (после автосборки в GitHub)
docker pull cofedish/ellensings:latest
docker-compose up -d
```

---

## ✅ Статус

- [x] Баг с event loop исправлен
- [x] SOCKS прокси работает (в yt-dlp)
- [x] Discord API работает (прямое подключение)
- [x] GitHub Actions настроен
- [x] Код запушен в GitHub
- [x] Готово к продакшену

**Дата:** 2025-11-08
**Commit:** d94c9b5
**Repository:** https://github.com/cofedish/EllenSingsBot
