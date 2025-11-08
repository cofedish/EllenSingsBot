# 🔧 Hotfix — Event Loop & Host Network

## Что исправлено

### 1. ❌ → ✅ Баг с event loop (SOCKS прокси)

**Проблема:**
```
ERROR | Failed to create proxy connector: no running event loop
```

**Причина:** `ProxyConnector.from_url()` вызывался в синхронном контексте (`__init__`), но требует event loop.

**Решение:** Перешли на синхронный способ создания connector:
```python
# До (не работало):
connector = ProxyConnector.from_url(proxy_url)

# После (работает):
from urllib.parse import urlparse
parsed = urlparse(proxy_url)
connector = ProxyConnector(
    proxy_type=ProxyType.SOCKS5,
    host=parsed.hostname,
    port=parsed.port or 1080,
    username=parsed.username,
    password=parsed.password,
    rdns=True
)
```

**Файл:** [bot.py:24-73](bot.py#L24-L73)

---

### 2. ❌ → ✅ Docker networking (127.0.0.1 для прокси на хосте)

**Проблема:** `127.0.0.1` внутри контейнера ≠ `127.0.0.1` на хосте

**Решение:** Добавлен `network_mode: host` для Linux (Ubuntu)

**Файл:** [compose.yml:12](compose.yml#L12)

```yaml
services:
  discord-bot:
    network_mode: host  # Контейнер в сети хоста
```

**Теперь работает:**
```env
PROXY_URL=socks5://127.0.0.1:2080
```

Ваш signbox на хосте доступен из контейнера как `localhost`!

---

## Как применить

### Вариант A: Пересобрать контейнер
```bash
docker-compose down
docker-compose up -d --build
```

### Вариант B: Быстрый перезапуск
```bash
docker-compose restart
```

---

## Проверка

Логи должны показать:
```
INFO | Using SOCKS proxy: socks5://127.0.0.1:2080
INFO | Logged in as YourBot
```

Без ошибки `no running event loop` ✅

---

## Дополнительно обновлено

- [.env.example](.env.example) — комментарии про host network
- [README.md:114-162](README.md#L114-L162) — секция "Docker Networking"
- [bot.py](bot.py) — синхронное создание ProxyConnector

---

**Дата:** 2025-11-08
**Статус:** Исправлено и готово к работе ✅
