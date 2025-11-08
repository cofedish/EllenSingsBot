"""
EllenSings - Discord музыкальный бот в стиле Ellen Joe
Поддерживает прокси, стабильную очередь, красивый UI
"""
import os
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv
import aiohttp

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-12s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger('bot')

load_dotenv()


def get_proxy_config():
    """
    Возвращает конфигурацию прокси из ENV для discord.py

    ВАЖНО: SOCKS прокси не поддерживается в discord.py напрямую
    (требует event loop при создании connector).
    SOCKS используется только в yt-dlp, не в Discord API.

    Returns:
        tuple: (connector, proxy_url, proxy_auth)
    """
    proxy_url = os.getenv('PROXY_URL')

    if not proxy_url:
        logger.info("No proxy configured, using direct connection")
        return None, None, None

    try:
        # SOCKS прокси - не поддерживается в Discord API
        # Будет использоваться только в yt-dlp
        if proxy_url.startswith('socks5://') or proxy_url.startswith('socks4://'):
            logger.info(f"SOCKS proxy detected: {proxy_url.split('@')[-1]}")
            logger.info("SOCKS proxy will be used for yt-dlp only (Discord API uses direct connection)")
            logger.info("This is normal - Discord API connects directly, music downloads go through proxy")
            return None, None, None

        # HTTP/HTTPS прокси - поддерживается discord.py напрямую
        # НЕ создаём connector - discord.py сам создаст правильный
        proxy_auth = None
        clean_url = proxy_url

        # Извлекаем авторизацию если есть
        if '@' in proxy_url:
            auth_part = proxy_url.split('//')[1].split('@')[0]
            if ':' in auth_part:
                username, password = auth_part.split(':', 1)
                proxy_auth = aiohttp.BasicAuth(username, password)
                # Убираем auth из URL
                clean_url = proxy_url.replace(f"{auth_part}@", "")

        logger.info(f"Using HTTP(S) proxy for Discord API: {clean_url.split('@')[-1]}")
        return None, clean_url, proxy_auth  # connector=None для HTTP прокси!

    except Exception as e:
        logger.error(f"Failed to parse proxy config: {e}")
        return None, None, None


class MusicBot(commands.Bot):
    """Основной класс бота с поддержкой прокси и музыки"""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

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

        self.initial_extensions = [
            'cogs.music'
        ]

    async def setup_hook(self):
        """Загрузка расширений и синхронизация команд"""
        logger.info("Loading extensions...")
        for ext in self.initial_extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"✓ Loaded: {ext}")
            except Exception as e:
                logger.error(f"✗ Failed to load {ext}: {e}")

        logger.info("Syncing slash commands...")
        try:
            synced = await self.tree.sync()
            logger.info(f"✓ Synced {len(synced)} slash commands")
        except Exception as e:
            logger.error(f"✗ Failed to sync commands: {e}")

    async def on_ready(self):
        """Событие: бот готов к работе"""
        logger.info("=" * 50)
        logger.info(f"Logged in as: {self.user}")
        logger.info(f"Bot ID: {self.user.id}")
        logger.info(f"Guilds: {len(self.guilds)}")
        logger.info("=" * 50)

        # Устанавливаем статус
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="/play | EllenSings 🎵"
            )
        )

    async def on_command_error(self, ctx, error):
        """Глобальная обработка ошибок команд"""
        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                title="❌ Ошибка",
                description=f"Отсутствует аргумент: `{error.param.name}`",
                color=0xFF6B6B
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

        logger.error(f"Command error: {error}", exc_info=error)

        embed = discord.Embed(
            title="❌ Произошла ошибка",
            description=str(error),
            color=0xFF6B6B
        )
        await ctx.send(embed=embed)


# Создаём и запускаем бота
bot = MusicBot()


@bot.command()
@commands.is_owner()
async def reload(ctx):
    """Перезагрузка всех cog'ов (только для владельца)"""
    logger.info(f"Reloading cogs requested by {ctx.author}")
    reloaded = []
    failed = []

    for ext in bot.initial_extensions:
        try:
            await bot.reload_extension(ext)
            reloaded.append(ext)
        except Exception as e:
            failed.append((ext, str(e)))
            logger.error(f"Failed to reload {ext}: {e}")

    embed = discord.Embed(
        title="🔄 Перезагрузка модулей",
        color=0x5BCEFA
    )

    if reloaded:
        embed.add_field(
            name="✅ Перезагружено",
            value="\n".join(f"`{ext}`" for ext in reloaded),
            inline=False
        )

    if failed:
        embed.add_field(
            name="❌ Ошибки",
            value="\n".join(f"`{ext}`: {err}" for ext, err in failed),
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command()
async def ping(ctx):
    """Проверка задержки бота"""
    latency_ms = round(bot.latency * 1000)

    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Задержка: `{latency_ms}ms`",
        color=0x5BCEFA
    )
    await ctx.send(embed=embed)


if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')

    if not token:
        logger.error("DISCORD_TOKEN not found in environment variables!")
        logger.error("Please set DISCORD_TOKEN in .env file")
        exit(1)

    try:
        logger.info("Starting EllenSings bot...")
        bot.run(token, log_handler=None)  # Используем наше логирование
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=e)
