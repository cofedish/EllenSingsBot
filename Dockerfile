FROM python:3.11-slim-bookworm

# Метаданные
LABEL maintainer="EllenSings Bot"
LABEL description="Discord music bot with proxy support"

# Установка системных зависимостей
# ffmpeg - для аудио обработки
# libopus/libsodium - для Discord voice
# iproute2/curl - для healthcheck и диагностики
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libswresample-dev \
    libopus-dev \
    libsodium-dev \
    libgirepository1.0-dev \
    libcairo2-dev \
    iproute2 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Создаём непривилегированного пользователя
RUN useradd -m -u 1000 -s /bin/bash botuser

WORKDIR /app

# Копируем зависимости и устанавливаем
COPY --chown=botuser:botuser requirements.txt .
RUN pip install --no-cache-dir --upgrade pip wheel \
    && pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY --chown=botuser:botuser . .

# Переключаемся на непривилегированного пользователя
USER botuser

# Health check - проверяем, что процесс бота запущен
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD pgrep -f "python.*bot.py" > /dev/null || exit 1

# Запуск бота
CMD ["python", "-u", "bot.py"]
