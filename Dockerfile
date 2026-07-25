# syntax=docker/dockerfile:1
# ============================================================
# EllenSings bot — multi-stage build, непривилегированный запуск.
# Сетевых привилегий у этого образа нет: прокси-маршрутизацию
# делает отдельный gateway-контейнер (см. gateway/).
# ============================================================

FROM python:3.11-slim-bookworm AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- runtime ----------
FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="EllenSings Bot"
LABEL org.opencontainers.image.description="Discord music bot (unprivileged; proxy handled by gateway container)"

# ffmpeg — декодирование/стриминг аудио
# libopus0 — кодек Discord Voice (загружается discord.py через ctypes)
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin bot

COPY --from=builder /install /usr/local

WORKDIR /app
COPY bot.py healthcheck.py ./
COPY cogs/ cogs/
COPY utils/ utils/

# Контейнер запускается с read_only rootfs; писать можно только в /tmp (tmpfs)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    HEALTH_FILE=/tmp/ellensings-health

USER bot

# Настоящая проверка живости: свежесть heartbeat-файла, который бот
# обновляет только пока WebSocket-соединение с Discord (через прокси) живо
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

ENTRYPOINT ["python", "-u", "bot.py"]
