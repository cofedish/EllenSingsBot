"""
YTDL обёртка с поддержкой прокси
Использует yt-dlp для загрузки аудио из YouTube и других источников
"""
import discord
import yt_dlp
import asyncio
import os
import logging

logger = logging.getLogger('ytdl')

# FFmpeg опции для стриминга
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -sn -dn -ignore_unknown -loglevel warning'
}


def get_ytdl_options():
    """
    Создаёт опции для yt-dlp

    ВАЖНО: При использовании tun2socks прокси настраивается на уровне сети,
    а не в приложении. yt-dlp будет автоматически использовать TUN интерфейс.
    """
    # Базовые опции
    options = {
        'format': 'bestaudio/best',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch',
        'source_address': '0.0.0.0',
        'socket_timeout': 60,
        'extractor_retries': 3,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
    }

    # tun2socks прозрачно проксирует весь трафик - настройка прокси не нужна
    # Проверяем для информации
    if os.getenv('SOCKS_PROXY'):
        logger.info("yt-dlp will use transparent proxy via tun2socks")

    return options


# Создаём глобальный экземпляр с текущими опциями
ytdl = yt_dlp.YoutubeDL(get_ytdl_options())


class YTDLSource(discord.PCMVolumeTransformer):
    """
    Источник аудио из YouTube/других платформ
    Поддерживает стриминг и прокси
    """

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
        Загружает трек по URL или поисковому запросу

        Args:
            url: URL или поисковый запрос
            loop: Event loop (опционально)
            stream: Стриминг (True) или скачивание (False)

        Returns:
            YTDLSource: Готовый источник аудио
        """
        loop = loop or asyncio.get_event_loop()

        try:
            # Извлекаем информацию о треке
            data = await loop.run_in_executor(
                None,
                lambda: ytdl.extract_info(url, download=not stream)
            )

            if data is None:
                raise Exception("Не удалось найти трек")

            # Если это плейлист - берём первый трек
            if 'entries' in data:
                # Берём первый доступный трек
                data = next((entry for entry in data['entries'] if entry), None)
                if data is None:
                    raise Exception("Плейлист пуст или недоступен")

            # URL для стриминга или имя файла
            if stream:
                filename = data['url']
            else:
                filename = ytdl.prepare_filename(data)

            logger.info(f"Loaded track: {data.get('title', 'Unknown')} from {data.get('extractor', 'unknown')}")

            # Создаём FFmpeg источник
            return cls(
                discord.FFmpegPCMAudio(filename, **ffmpeg_options),
                data=data
            )

        except yt_dlp.DownloadError as e:
            error_msg = str(e)
            logger.error(f"yt-dlp download error: {error_msg}")

            # Более дружелюбные сообщения об ошибках
            if "Video unavailable" in error_msg:
                raise Exception("Видео недоступно или удалено")
            elif "Private video" in error_msg:
                raise Exception("Это приватное видео")
            elif "Sign in" in error_msg:
                raise Exception("Требуется вход в аккаунт (недоступно)")
            elif "not available" in error_msg:
                raise Exception("Контент недоступен в вашем регионе")
            else:
                raise Exception(f"Ошибка загрузки: {error_msg}")

        except Exception as e:
            logger.error(f"Unexpected error in YTDLSource: {e}")
            raise Exception(f"Не удалось загрузить трек: {str(e)}")

    def __str__(self):
        return f"{self.title} ({self.uploader})"
