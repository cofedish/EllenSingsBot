"""
Обёртка над yt-dlp.

Прокси настраивается на уровне сети (gateway-контейнер с tun2socks),
поэтому здесь нет никакой прокси-конфигурации и подмены сертификатов:
TLS-проверка включена, заголовками управляет сам yt-dlp.
"""
import asyncio
import logging
import os
import tempfile
from urllib.parse import urlparse

import discord
import yt_dlp

logger = logging.getLogger('ytdl')

# FFmpeg опции для стриминга
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -sn -dn -ignore_unknown -loglevel warning'
}

ALLOWED_URL_SCHEMES = {'http', 'https'}


def validate_query(query: str) -> str:
    """
    Пропускает только http(s)-ссылки или обычный поисковый текст.

    Блокирует схемы вроде file://, ftp:// и т.п., которые пользователь
    может подсунуть в /play.
    """
    query = query.strip()
    if '://' in query:
        scheme = urlparse(query).scheme.lower()
        if scheme not in ALLOWED_URL_SCHEMES:
            raise ValueError('Поддерживаются только http/https ссылки')
    return query


def _base_options() -> dict:
    return {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(tempfile.gettempdir(), '%(extractor)s-%(id)s.%(ext)s'),
        'restrictfilenames': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch',
        'socket_timeout': 60,
        'extractor_retries': 3,
        'cachedir': False,  # контейнер запускается read-only
    }


# Экземпляр для одиночных треков и поиска: URL "видео+плейлист" не тянет весь плейлист
ytdl = yt_dlp.YoutubeDL({**_base_options(), 'noplaylist': True})

# Экземпляр для команды /playlist: плейлисты разрешены
ytdl_playlist = yt_dlp.YoutubeDL({**_base_options(), 'noplaylist': False})


class YTDLSource(discord.PCMVolumeTransformer):
    """Источник аудио из YouTube/других платформ (стриминг через ffmpeg)"""

    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown')
        self.url = data.get('url')
        self.webpage_url = data.get('webpage_url')
        self.duration = data.get('duration', 0)
        self.thumbnail = data.get('thumbnail')
        self.uploader = data.get('uploader', 'Unknown')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        """
        Загружает трек по URL или поисковому запросу.

        Args:
            url: URL (http/https) или поисковый запрос
            loop: Event loop (опционально)
            stream: Стриминг (True) или скачивание (False)

        Returns:
            YTDLSource: Готовый источник аудио
        """
        loop = loop or asyncio.get_running_loop()
        url = validate_query(url)

        try:
            data = await loop.run_in_executor(
                None,
                lambda: ytdl.extract_info(url, download=not stream)
            )

            if data is None:
                raise ValueError("Не удалось найти трек")

            # Если это результат поиска/плейлист — берём первый доступный трек
            if 'entries' in data:
                data = next((entry for entry in data['entries'] if entry), None)
                if data is None:
                    raise ValueError("Ничего не найдено")

            filename = data['url'] if stream else ytdl.prepare_filename(data)

            logger.info(
                "Loaded track: %s from %s",
                data.get('title', 'Unknown'), data.get('extractor', 'unknown')
            )

            return cls(
                discord.FFmpegPCMAudio(filename, **ffmpeg_options),
                data=data
            )

        except yt_dlp.DownloadError as e:
            error_msg = str(e)
            logger.error("yt-dlp download error: %s", error_msg)

            # Более дружелюбные сообщения об ошибках
            if "Video unavailable" in error_msg:
                raise ValueError("Видео недоступно или удалено") from e
            elif "Private video" in error_msg:
                raise ValueError("Это приватное видео") from e
            elif "Sign in" in error_msg:
                raise ValueError("Требуется вход в аккаунт (недоступно)") from e
            elif "not available" in error_msg:
                raise ValueError("Контент недоступен в вашем регионе") from e
            else:
                raise ValueError("Не удалось загрузить трек") from e

        except ValueError:
            raise

        except Exception as e:
            logger.error("Unexpected error in YTDLSource: %s", e)
            raise ValueError("Не удалось загрузить трек") from e

    def __str__(self):
        return f"{self.title} ({self.uploader})"
