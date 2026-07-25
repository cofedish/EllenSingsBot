"""
Docker healthcheck для контейнера бота.

Проверяет свежесть heartbeat-файла, который bot.py обновляет только пока
WebSocket-соединение с Discord живо. Устаревший файл означает, что бот завис,
потерял соединение или маршрут через прокси не работает — а не просто
"процесс существует".
"""
import os
import sys
import tempfile
import time

HEALTH_FILE = os.getenv('HEALTH_FILE') or os.path.join(tempfile.gettempdir(), 'ellensings-health')
MAX_AGE_SECONDS = int(os.getenv('HEALTH_MAX_AGE', '90'))


def main() -> int:
    try:
        age = time.time() - os.stat(HEALTH_FILE).st_mtime
    except OSError:
        return 1
    return 0 if age <= MAX_AGE_SECONDS else 1


if __name__ == '__main__':
    sys.exit(main())
