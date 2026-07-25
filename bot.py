"""
EllenSings - Discord музыкальный бот в стиле Ellen Joe

Прокси настраивается на уровне сети в отдельном gateway-контейнере
(tun2socks + kill-switch), поэтому в коде бота никакой прокси-логики нет.
"""
import asyncio
import logging
import math
import os
import signal
import tempfile
import time
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-12s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger('bot')

load_dotenv()

# Файл-heartbeat: обновляется только пока бот реально подключён к Discord.
# Docker healthcheck (healthcheck.py) проверяет его свежесть — так проверяется
# и живость процесса, и работоспособность маршрута через прокси.
HEARTBEAT_FILE = Path(
    os.getenv('HEALTH_FILE') or os.path.join(tempfile.gettempdir(), 'ellensings-health')
)


def read_token() -> str | None:
    """
    Токен берём из DISCORD_TOKEN_FILE (Docker secret) или DISCORD_TOKEN (env).
    Сам токен нигде не логируется.
    """
    token_file = os.getenv('DISCORD_TOKEN_FILE')
    if token_file:
        try:
            return Path(token_file).read_text(encoding='utf-8').strip()
        except OSError as e:
            logger.error(f"Cannot read DISCORD_TOKEN_FILE: {e}")
            return None
    return os.getenv('DISCORD_TOKEN')


class MusicBot(commands.Bot):
    """Основной класс бота"""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
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

        self.heartbeat_loop.start()

    @tasks.loop(seconds=30)
    async def heartbeat_loop(self):
        """Пишет heartbeat-файл, пока соединение с Discord живо"""
        # isfinite отфильтровывает nan (нет данных) и inf (нет соединения)
        if self.is_ready() and math.isfinite(self.latency):
            try:
                HEARTBEAT_FILE.write_text(str(int(time.time())), encoding='utf-8')
            except OSError as e:
                logger.warning(f"Cannot write heartbeat file: {e}")

    async def close(self):
        """Корректное завершение: останавливаем voice-клиенты и heartbeat"""
        logger.info("Shutting down...")
        self.heartbeat_loop.cancel()
        for vc in list(self.voice_clients):
            try:
                await vc.disconnect(force=True)
            except Exception as e:
                logger.warning(f"Failed to disconnect voice client: {e}")
        await super().close()

    async def on_ready(self):
        """Событие: бот готов к работе"""
        logger.info("=" * 50)
        logger.info(f"Logged in as: {self.user}")
        logger.info(f"Bot ID: {self.user.id}")
        logger.info(f"Guilds: {len(self.guilds)}")
        logger.info("=" * 50)

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

        # Ошибки, возникшие внутри тела команды, приходят обёрнутыми
        if isinstance(error, commands.CommandInvokeError):
            error = error.original

        if isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                title="❌ Ошибка",
                description=f"Отсутствует аргумент: `{error.param.name}`",
                color=0xFF6B6B
            )
            try:
                await ctx.send(embed=embed, ephemeral=True)
            except discord.NotFound:
                logger.warning("Could not send error message: interaction expired")
            return

        if isinstance(error, commands.CheckFailure):
            embed = discord.Embed(
                title="❌ Недостаточно прав",
                description=str(error) or "Команда недоступна",
                color=0xFF6B6B
            )
            try:
                await ctx.send(embed=embed, ephemeral=True)
            except (discord.NotFound, discord.HTTPException):
                pass
            return

        logger.error(f"Command error: {error}", exc_info=error)

        # Пользователю — общее сообщение без внутренних деталей
        embed = discord.Embed(
            title="❌ Произошла ошибка",
            description=str(error) if isinstance(error, ValueError) else "Что-то пошло не так, попробуйте ещё раз",
            color=0xFF6B6B
        )

        try:
            await ctx.send(embed=embed)
        except discord.NotFound:
            logger.warning("Could not send error message: interaction expired")
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")


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


@bot.hybrid_command(name="ping", description="Проверить задержку бота")
async def ping(ctx):
    """Проверка задержки бота"""
    latency_ms = round(bot.latency * 1000)

    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Задержка: `{latency_ms}ms`",
        color=0x5BCEFA
    )
    await ctx.send(embed=embed)


async def main() -> int:
    token = read_token()
    if not token:
        logger.error("DISCORD_TOKEN not found!")
        logger.error("Set DISCORD_TOKEN (env / .env) or DISCORD_TOKEN_FILE (Docker secret)")
        return 1

    loop = asyncio.get_running_loop()

    def request_shutdown(sig_name: str):
        logger.info(f"Received {sig_name}, closing bot...")
        # close() идемпотентен: повторный сигнал не ломает завершение
        asyncio.ensure_future(bot.close())

    # SIGTERM шлёт docker stop; SIGINT — Ctrl+C.
    # На Windows add_signal_handler недоступен — там сработает KeyboardInterrupt.
    for sig_name in ('SIGTERM', 'SIGINT'):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, request_shutdown, sig_name)
        except NotImplementedError:
            pass

    logger.info("Starting EllenSings bot...")
    async with bot:
        await bot.start(token)

    logger.info("Bot stopped cleanly")
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
