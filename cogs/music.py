"""
Music Cog для Discord бота EllenSings
Управление музыкальной очередью, воспроизведением и UI
"""
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import random
import os
from typing import Optional, Dict, List
from utils.ytdl import YTDLSource
from discord.ui import View, Button
import logging

logger = logging.getLogger('music')


class QueuePaginator(View):
    """Пагинация для отображения очереди треков"""
    def __init__(self, cog, guild_id: int, page: int = 0):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.page = page

    def get_queue_embed(self) -> discord.Embed:
        """Создаёт embed с очередью треков"""
        queue = self.cog.get_queue(self.guild_id)
        current = self.cog.current.get(self.guild_id)

        # Стиль Ellen Joe: минималистичный, чистый
        embed = discord.Embed(
            title="🎵 Очередь воспроизведения",
            color=0x5BCEFA,  # Мягкий голубой
            description=""
        )

        # Текущий трек
        if current:
            embed.add_field(
                name="▶️ Сейчас играет",
                value=f"**{current.title}**",
                inline=False
            )

        # Следующие треки с пагинацией
        items_per_page = 10
        start = self.page * items_per_page
        end = start + items_per_page
        page_queue = queue[start:end]

        if page_queue:
            queue_text = "\n".join([
                f"`{start + i + 1}.` {track.title}"
                for i, track in enumerate(page_queue)
            ])
            embed.add_field(
                name=f"📃 Следующие ({len(queue)} треков всего)",
                value=queue_text,
                inline=False
            )
        elif not current:
            embed.description = "*Очередь пуста*"

        # Режим повтора
        repeat_mode = self.cog.repeat_mode.get(self.guild_id, 'none')
        repeat_icons = {'none': '➡️', 'track': '🔂', 'queue': '🔁'}
        embed.set_footer(text=f"{repeat_icons[repeat_mode]} Режим: {repeat_mode}")

        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.grey)
    async def prev_page(self, interaction: discord.Interaction, button: Button):
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.get_queue_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.grey)
    async def next_page(self, interaction: discord.Interaction, button: Button):
        queue = self.cog.get_queue(self.guild_id)
        max_page = (len(queue) - 1) // 10
        if self.page < max_page:
            self.page += 1
            await interaction.response.edit_message(embed=self.get_queue_embed(), view=self)
        else:
            await interaction.response.defer()


class MusicControls(View):
    """Кнопки управления воспроизведением в стиле Ellen Joe"""
    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, custom_id="play_pause")
    async def play_pause_btn(self, interaction: discord.Interaction, button: Button):
        """Пауза/Возобновление"""
        await self.cog.toggle_play_pause(self.guild_id)
        await interaction.response.defer()
        await self.cog.update_now_playing(self.guild_id)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="skip")
    async def skip_btn(self, interaction: discord.Interaction, button: Button):
        """Пропуск трека"""
        guild = self.cog.bot.get_guild(self.guild_id)
        if guild and guild.voice_client:
            guild.voice_client.stop()
            await interaction.response.send_message("⏭️ Трек пропущен", ephemeral=True, delete_after=3)
        else:
            await interaction.response.send_message("❌ Ничего не играет", ephemeral=True, delete_after=3)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="stop")
    async def stop_btn(self, interaction: discord.Interaction, button: Button):
        """Остановка и очистка"""
        await self.cog.stop_playback(self.guild_id)
        await interaction.response.send_message("⏹️ Воспроизведение остановлено", ephemeral=True, delete_after=3)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="repeat")
    async def repeat_btn(self, interaction: discord.Interaction, button: Button):
        """Переключение режима повтора"""
        modes = ['none', 'track', 'queue']
        current = self.cog.repeat_mode.get(self.guild_id, 'none')
        next_mode = modes[(modes.index(current) + 1) % len(modes)]
        self.cog.repeat_mode[self.guild_id] = next_mode

        mode_names = {'none': 'Без повтора', 'track': 'Повтор трека', 'queue': 'Повтор очереди'}
        await interaction.response.send_message(
            f"🔁 {mode_names[next_mode]}",
            ephemeral=True,
            delete_after=3
        )
        await self.cog.update_now_playing(self.guild_id)

    @discord.ui.button(emoji="📃", style=discord.ButtonStyle.secondary, custom_id="queue")
    async def queue_btn(self, interaction: discord.Interaction, button: Button):
        """Показать очередь"""
        paginator = QueuePaginator(self.cog, self.guild_id)
        await interaction.response.send_message(
            embed=paginator.get_queue_embed(),
            view=paginator,
            ephemeral=True
        )


class Music(commands.Cog):
    """Основной музыкальный модуль с улучшенной стабильностью"""

    def __init__(self, bot):
        self.bot = bot
        # Состояние для каждой гильдии
        self.queues: Dict[int, List] = {}
        self.current: Dict[int, discord.PCMVolumeTransformer] = {}
        self.repeat_mode: Dict[int, str] = {}  # 'none', 'track', 'queue'
        self.queue_locks: Dict[int, asyncio.Lock] = {}
        self.inactive_timers: Dict[int, asyncio.Task] = {}
        self.now_playing_messages: Dict[int, discord.Message] = {}

        logger.info("Music cog loaded")

    def get_queue(self, guild_id: int) -> List:
        """Получить очередь для гильдии"""
        return self.queues.setdefault(guild_id, [])

    def get_lock(self, guild_id: int) -> asyncio.Lock:
        """Получить lock для очереди гильдии"""
        if guild_id not in self.queue_locks:
            self.queue_locks[guild_id] = asyncio.Lock()
        return self.queue_locks[guild_id]

    async def process_queue(self, guild_id: int):
        """
        ЕДИНАЯ точка обработки очереди с lock для предотвращения race conditions
        """
        lock = self.get_lock(guild_id)

        async with lock:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return

            voice_client = guild.voice_client
            if not voice_client or not voice_client.is_connected():
                return

            # Если уже играет - ничего не делаем
            if voice_client.is_playing() or voice_client.is_paused():
                return

            queue = self.get_queue(guild_id)

            # Если очередь пуста - запускаем таймер отключения
            if not queue:
                self.start_inactivity_timer(guild_id)
                return

            # Отменяем таймер, если он был
            self.cancel_inactivity_timer(guild_id)

            # Берём следующий трек
            player = queue.pop(0)
            self.current[guild_id] = player

            # Запускаем воспроизведение
            def after_play(error):
                if error:
                    logger.error(f"Playback error in guild {guild_id}: {error}")
                # Запускаем обработку следующего трека
                asyncio.run_coroutine_threadsafe(
                    self.handle_track_end(guild_id),
                    self.bot.loop
                )

            voice_client.play(player, after=after_play)
            logger.info(f"Playing: {player.title} in guild {guild_id}")

            # Обновляем панель Now Playing
            await self.update_now_playing(guild_id)

    async def handle_track_end(self, guild_id: int):
        """
        Обработка окончания трека с учётом режима повтора
        """
        current_track = self.current.get(guild_id)

        # Обработка режима повтора
        if current_track:
            repeat = self.repeat_mode.get(guild_id, 'none')

            if repeat == 'track':
                # Повтор текущего трека - добавляем в начало очереди
                self.get_queue(guild_id).insert(0, current_track)
            elif repeat == 'queue':
                # Повтор очереди - добавляем в конец
                self.get_queue(guild_id).append(current_track)

        # Обрабатываем следующий трек
        await self.process_queue(guild_id)

    def start_inactivity_timer(self, guild_id: int):
        """Запускает таймер на отключение при неактивности (10 минут)"""
        self.cancel_inactivity_timer(guild_id)

        async def timer():
            try:
                await asyncio.sleep(600)  # 10 минут
                await self.stop_playback(guild_id)
                logger.info(f"Disconnected from guild {guild_id} due to inactivity")
            except asyncio.CancelledError:
                pass

        self.inactive_timers[guild_id] = asyncio.create_task(timer())

    def cancel_inactivity_timer(self, guild_id: int):
        """Отменяет таймер неактивности"""
        if guild_id in self.inactive_timers:
            self.inactive_timers[guild_id].cancel()
            del self.inactive_timers[guild_id]

    async def stop_playback(self, guild_id: int):
        """Полная остановка воспроизведения и очистка состояния"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        voice_client = guild.voice_client
        if voice_client:
            voice_client.stop()
            await voice_client.disconnect()

        # Очистка состояния
        self.queues.pop(guild_id, None)
        self.current.pop(guild_id, None)
        self.repeat_mode.pop(guild_id, None)
        self.cancel_inactivity_timer(guild_id)

        # Удаляем панель управления
        if guild_id in self.now_playing_messages:
            try:
                await self.now_playing_messages[guild_id].delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            del self.now_playing_messages[guild_id]

    async def toggle_play_pause(self, guild_id: int):
        """Переключение паузы/воспроизведения"""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        voice_client = guild.voice_client
        if not voice_client:
            return

        if voice_client.is_playing():
            voice_client.pause()
        elif voice_client.is_paused():
            voice_client.resume()

    async def update_now_playing(self, guild_id: int):
        """Обновляет embed с текущим треком"""
        current = self.current.get(guild_id)
        if not current:
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        voice_client = guild.voice_client
        if not voice_client:
            return

        # Создаём embed в стиле Ellen Joe
        embed = discord.Embed(
            title="🎧 Сейчас играет",
            description=f"**{current.title}**",
            color=0x5BCEFA
        )

        # Статус воспроизведения
        if voice_client.is_paused():
            status = "⏸️ Пауза"
        elif voice_client.is_playing():
            status = "▶️ Воспроизведение"
        else:
            status = "⏹️ Остановлено"

        embed.add_field(name="Статус", value=status, inline=True)

        # Информация об очереди
        queue_len = len(self.get_queue(guild_id))
        embed.add_field(name="В очереди", value=f"{queue_len} треков", inline=True)

        # Режим повтора
        repeat = self.repeat_mode.get(guild_id, 'none')
        repeat_icons = {'none': '➡️', 'track': '🔂', 'queue': '🔁'}
        embed.add_field(name="Режим", value=f"{repeat_icons[repeat]} {repeat}", inline=True)

        embed.set_footer(text="EllenSings • Музыкальный сервис")

        # Создаём или обновляем сообщение
        view = MusicControls(self, guild_id)

        if guild_id in self.now_playing_messages:
            try:
                await self.now_playing_messages[guild_id].edit(embed=embed, view=view)
            except (discord.NotFound, discord.HTTPException):
                # Сообщение удалено, создаём новое
                del self.now_playing_messages[guild_id]

    # ========== КОМАНДЫ ==========

    @commands.hybrid_command(name="play", description="Включить музыку")
    @app_commands.describe(query="Название трека или URL")
    async def play(self, ctx: commands.Context, *, query: str):
        """Добавить трек в очередь и начать воспроизведение"""

        # Проверка: пользователь в голосовом канале
        if not ctx.author.voice:
            embed = discord.Embed(
                title="❌ Ошибка",
                description="Вы должны находиться в голосовом канале",
                color=0xFF6B6B
            )
            return await ctx.send(embed=embed, ephemeral=True)

        # Подключаемся к каналу, если ещё не подключены
        voice_client = ctx.voice_client
        if not voice_client:
            try:
                voice_client = await ctx.author.voice.channel.connect()
                logger.info(f"Connected to voice channel in guild {ctx.guild.id}")
            except Exception as e:
                logger.error(f"Failed to connect to voice: {e}")
                embed = discord.Embed(
                    title="❌ Ошибка подключения",
                    description="Не удалось подключиться к голосовому каналу",
                    color=0xFF6B6B
                )
                return await ctx.send(embed=embed)

        # Загрузка трека
        await ctx.defer()

        try:
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)

            # Добавляем в очередь
            queue = self.get_queue(ctx.guild.id)
            queue.append(player)

            # Создаём embed подтверждения
            embed = discord.Embed(
                title="✅ Добавлено в очередь",
                description=f"**{player.title}**",
                color=0x98D8C8
            )
            embed.add_field(name="Позиция", value=f"#{len(queue)}", inline=True)
            embed.set_footer(text="EllenSings")

            await ctx.send(embed=embed)

            # Запускаем обработку очереди
            await self.process_queue(ctx.guild.id)

        except Exception as e:
            logger.error(f"Error loading track: {e}")
            embed = discord.Embed(
                title="❌ Ошибка загрузки",
                description=f"Не удалось загрузить трек: {str(e)}",
                color=0xFF6B6B
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="skip", description="Пропустить текущий трек")
    async def skip(self, ctx: commands.Context):
        """Пропуск текущего трека"""
        voice_client = ctx.voice_client

        if not voice_client or not voice_client.is_connected():
            embed = discord.Embed(
                title="❌ Ошибка",
                description="Бот не подключён к голосовому каналу",
                color=0xFF6B6B
            )
            return await ctx.send(embed=embed, ephemeral=True)

        if not voice_client.is_playing() and not voice_client.is_paused():
            embed = discord.Embed(
                title="❌ Ошибка",
                description="Сейчас ничего не играет",
                color=0xFF6B6B
            )
            return await ctx.send(embed=embed, ephemeral=True)

        voice_client.stop()

        embed = discord.Embed(
            title="⏭️ Трек пропущен",
            color=0x5BCEFA
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="stop", description="Остановить воспроизведение и очистить очередь")
    async def stop(self, ctx: commands.Context):
        """Полная остановка"""
        await self.stop_playback(ctx.guild.id)

        embed = discord.Embed(
            title="⏹️ Остановлено",
            description="Воспроизведение остановлено, очередь очищена",
            color=0x95E1D3
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="pause", description="Приостановить воспроизведение")
    async def pause(self, ctx: commands.Context):
        """Пауза"""
        voice_client = ctx.voice_client

        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await self.update_now_playing(ctx.guild.id)
            embed = discord.Embed(title="⏸️ Пауза", color=0x5BCEFA)
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Ошибка",
                description="Сейчас ничего не играет",
                color=0xFF6B6B
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name="resume", description="Возобновить воспроизведение")
    async def resume(self, ctx: commands.Context):
        """Возобновление"""
        voice_client = ctx.voice_client

        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await self.update_now_playing(ctx.guild.id)
            embed = discord.Embed(title="▶️ Возобновлено", color=0x5BCEFA)
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Ошибка",
                description="Воспроизведение не на паузе",
                color=0xFF6B6B
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name="queue", description="Показать очередь треков")
    async def queue_cmd(self, ctx: commands.Context):
        """Отображение очереди с пагинацией"""
        paginator = QueuePaginator(self, ctx.guild.id)
        await ctx.send(embed=paginator.get_queue_embed(), view=paginator)

    @commands.hybrid_command(name="nowplaying", description="Показать текущий трек")
    @app_commands.describe()
    async def nowplaying(self, ctx: commands.Context):
        """Показать текущий трек с панелью управления"""
        current = self.current.get(ctx.guild.id)

        if not current:
            embed = discord.Embed(
                title="❌ Ничего не играет",
                color=0xFF6B6B
            )
            return await ctx.send(embed=embed, ephemeral=True)

        voice_client = ctx.voice_client

        embed = discord.Embed(
            title="🎧 Сейчас играет",
            description=f"**{current.title}**",
            color=0x5BCEFA
        )

        if voice_client:
            if voice_client.is_paused():
                status = "⏸️ Пауза"
            elif voice_client.is_playing():
                status = "▶️ Воспроизведение"
            else:
                status = "⏹️ Остановлено"
            embed.add_field(name="Статус", value=status, inline=True)

        queue_len = len(self.get_queue(ctx.guild.id))
        embed.add_field(name="В очереди", value=f"{queue_len} треков", inline=True)

        repeat = self.repeat_mode.get(ctx.guild.id, 'none')
        repeat_icons = {'none': '➡️', 'track': '🔂', 'queue': '🔁'}
        embed.add_field(name="Режим", value=f"{repeat_icons[repeat]} {repeat}", inline=True)

        embed.set_footer(text="EllenSings • Музыкальный сервис")

        view = MusicControls(self, ctx.guild.id)
        message = await ctx.send(embed=embed, view=view)

        # Сохраняем сообщение для обновлений
        self.now_playing_messages[ctx.guild.id] = message

    @commands.hybrid_command(name="clear", description="Очистить очередь")
    async def clear(self, ctx: commands.Context):
        """Очистить очередь (не останавливая текущий трек)"""
        queue = self.get_queue(ctx.guild.id)
        cleared = len(queue)
        queue.clear()

        embed = discord.Embed(
            title="🗑️ Очередь очищена",
            description=f"Удалено треков: {cleared}",
            color=0x95E1D3
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="repeat", description="Установить режим повтора")
    @app_commands.describe(mode="Режим: none, track, queue")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Без повтора", value="none"),
        app_commands.Choice(name="Повтор трека", value="track"),
        app_commands.Choice(name="Повтор очереди", value="queue")
    ])
    async def repeat(self, ctx: commands.Context, mode: str = None):
        """Управление режимом повтора"""
        if mode is None:
            # Переключение по кругу
            modes = ['none', 'track', 'queue']
            current = self.repeat_mode.get(ctx.guild.id, 'none')
            mode = modes[(modes.index(current) + 1) % len(modes)]

        mode = mode.lower()
        if mode not in ['none', 'track', 'queue']:
            embed = discord.Embed(
                title="❌ Ошибка",
                description="Доступные режимы: none, track, queue",
                color=0xFF6B6B
            )
            return await ctx.send(embed=embed, ephemeral=True)

        self.repeat_mode[ctx.guild.id] = mode

        mode_names = {
            'none': '➡️ Без повтора',
            'track': '🔂 Повтор трека',
            'queue': '🔁 Повтор очереди'
        }

        embed = discord.Embed(
            title="🔁 Режим повтора",
            description=mode_names[mode],
            color=0x5BCEFA
        )
        await ctx.send(embed=embed)
        await self.update_now_playing(ctx.guild.id)


async def setup(bot):
    await bot.add_cog(Music(bot))
