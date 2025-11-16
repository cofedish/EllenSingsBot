"""
Music Cog для Discord бота EllenSings
Управление музыкальной очередью, воспроизведением и UI
🎵 Ellen Joe Theme - минималистичный, стильный дизайн
"""
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import random
import os
from typing import Optional, Dict, List
from utils.ytdl import YTDLSource
from discord.ui import View, Button, Select
import logging
from datetime import timedelta

logger = logging.getLogger('music')

# Ellen Joe брендинг
ELLEN_COLOR = 0x5BCEFA  # Голубой Ellen
ELLEN_AVATAR = "https://i.imgur.com/9qX4r8Y.png"  # Ellen Joe аватар
ELLEN_BANNER = "https://i.imgur.com/3kZw7xM.png"  # Ellen Joe баннер


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
            color=ELLEN_COLOR,
            description=""
        )

        # Баннер Ellen Joe
        embed.set_author(name="EllenSings Music Bot", icon_url=ELLEN_AVATAR)

        # Текущий трек с деталями
        if current:
            duration = str(timedelta(seconds=current.duration)) if current.duration else "Live"
            current_text = f"**[{current.title}]({current.webpage_url})**\n"
            current_text += f"👤 {current.uploader} • ⏱️ {duration}"

            embed.add_field(
                name="▶️ Сейчас играет",
                value=current_text,
                inline=False
            )

            # Thumbnail текущего трека
            if current.thumbnail:
                embed.set_thumbnail(url=current.thumbnail)

        # Следующие треки с пагинацией
        items_per_page = 8
        start = self.page * items_per_page
        end = start + items_per_page
        page_queue = queue[start:end]

        if page_queue:
            queue_text = ""
            for i, track in enumerate(page_queue):
                duration = str(timedelta(seconds=track.duration)) if track.duration else "Live"
                queue_text += f"`{start + i + 1}.` **{track.title[:50]}**\n"
                queue_text += f"    ⏱️ {duration} • 👤 {track.uploader[:30]}\n"

            embed.add_field(
                name=f"📃 Следующие треки (всего: {len(queue)})",
                value=queue_text,
                inline=False
            )
        elif not current:
            embed.description = "*Очередь пуста. Добавьте треки командой `/play`*"
            embed.set_image(url=ELLEN_BANNER)

        # Информация внизу
        repeat_mode = self.cog.repeat_mode.get(self.guild_id, 'none')
        shuffle_status = "🔀 Вкл" if self.cog.shuffle_mode.get(self.guild_id) else "➡️ Выкл"
        repeat_icons = {'none': '➡️ Выкл', 'track': '🔂 Трек', 'queue': '🔁 Очередь'}

        embed.set_footer(
            text=f"Повтор: {repeat_icons[repeat_mode]} | Shuffle: {shuffle_status} | Страница {self.page + 1}",
            icon_url=ELLEN_AVATAR
        )

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


class SearchResultsView(View):
    """Интерфейс выбора из результатов поиска"""
    def __init__(self, cog, ctx, results: List[dict]):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.results = results[:10]  # Макс 10 результатов

        # Создаём select menu с результатами
        options = []
        for i, result in enumerate(self.results):
            duration = str(timedelta(seconds=result.get('duration', 0))) if result.get('duration') else "Live"
            options.append(
                discord.SelectOption(
                    label=result['title'][:100],
                    description=f"{result.get('uploader', 'Unknown')[:50]} • {duration}",
                    value=str(i),
                    emoji="🎵"
                )
            )

        self.select = Select(
            placeholder="Выберите трек...",
            options=options,
            custom_id="search_select"
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        """Обработка выбора трека"""
        selected_idx = int(self.select.values[0])
        selected = self.results[selected_idx]

        await interaction.response.defer()

        try:
            # Добавляем в очередь
            player = await YTDLSource.from_url(
                selected['webpage_url'],
                loop=self.cog.bot.loop,
                stream=True
            )

            queue = self.cog.get_queue(self.ctx.guild.id)
            queue.append(player)

            # Embed подтверждения
            embed = discord.Embed(
                title="✅ Добавлено в очередь",
                description=f"**[{player.title}]({player.webpage_url})**",
                color=ELLEN_COLOR
            )
            embed.set_thumbnail(url=player.thumbnail)
            embed.add_field(name="Позиция", value=f"#{len(queue)}", inline=True)
            duration = str(timedelta(seconds=player.duration)) if player.duration else "Live"
            embed.add_field(name="Длительность", value=duration, inline=True)
            embed.set_footer(text=f"Запросил {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

            await interaction.followup.send(embed=embed)

            # Запускаем воспроизведение
            await self.cog.process_queue(self.ctx.guild.id)

        except Exception as e:
            logger.error(f"Error adding track from search: {e}")
            await interaction.followup.send(f"❌ Ошибка: {str(e)}", ephemeral=True)


class MusicControls(View):
    """Кнопки управления воспроизведением в стиле Ellen Joe"""
    def __init__(self, cog, guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, custom_id="play_pause", row=0)
    async def play_pause_btn(self, interaction: discord.Interaction, button: Button):
        """Пауза/Возобновление"""
        await self.cog.toggle_play_pause(self.guild_id)
        await interaction.response.defer()
        await self.cog.update_now_playing(self.guild_id)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="skip", row=0)
    async def skip_btn(self, interaction: discord.Interaction, button: Button):
        """Пропуск трека"""
        guild = self.cog.bot.get_guild(self.guild_id)
        if guild and guild.voice_client:
            guild.voice_client.stop()
            await interaction.response.send_message("⏭️ Трек пропущен", ephemeral=True, delete_after=3)
        else:
            await interaction.response.send_message("❌ Ничего не играет", ephemeral=True, delete_after=3)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="stop", row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: Button):
        """Остановка и очистка"""
        await self.cog.stop_playback(self.guild_id)
        await interaction.response.send_message("⏹️ Воспроизведение остановлено", ephemeral=True, delete_after=3)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="repeat", row=0)
    async def repeat_btn(self, interaction: discord.Interaction, button: Button):
        """Переключение режима повтора"""
        modes = ['none', 'track', 'queue']
        current = self.cog.repeat_mode.get(self.guild_id, 'none')
        next_mode = modes[(modes.index(current) + 1) % len(modes)]
        self.cog.repeat_mode[self.guild_id] = next_mode

        mode_names = {'none': '➡️ Без повтора', 'track': '🔂 Повтор трека', 'queue': '🔁 Повтор очереди'}
        await interaction.response.send_message(
            f"{mode_names[next_mode]}",
            ephemeral=True,
            delete_after=3
        )
        await self.cog.update_now_playing(self.guild_id)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="shuffle", row=0)
    async def shuffle_btn(self, interaction: discord.Interaction, button: Button):
        """Перемешать очередь"""
        queue = self.cog.get_queue(self.guild_id)
        if len(queue) < 2:
            await interaction.response.send_message("❌ Недостаточно треков для перемешивания", ephemeral=True, delete_after=3)
            return

        random.shuffle(queue)
        shuffle_mode = self.cog.shuffle_mode.get(self.guild_id, False)
        self.cog.shuffle_mode[self.guild_id] = not shuffle_mode

        await interaction.response.send_message(
            f"🔀 Очередь перемешана ({len(queue)} треков)",
            ephemeral=True,
            delete_after=3
        )
        await self.cog.update_now_playing(self.guild_id)

    @discord.ui.button(emoji="📃", style=discord.ButtonStyle.secondary, custom_id="queue", row=1)
    async def queue_btn(self, interaction: discord.Interaction, button: Button):
        """Показать очередь"""
        paginator = QueuePaginator(self.cog, self.guild_id)
        await interaction.response.send_message(
            embed=paginator.get_queue_embed(),
            view=paginator,
            ephemeral=True
        )

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, custom_id="volume_up", row=1)
    async def volume_up_btn(self, interaction: discord.Interaction, button: Button):
        """Увеличить громкость"""
        current = self.cog.current.get(self.guild_id)
        if current:
            new_volume = min(current.volume + 0.1, 2.0)
            current.volume = new_volume
            await interaction.response.send_message(
                f"🔊 Громкость: {int(new_volume * 100)}%",
                ephemeral=True,
                delete_after=3
            )
            await self.cog.update_now_playing(self.guild_id)
        else:
            await interaction.response.send_message("❌ Ничего не играет", ephemeral=True, delete_after=3)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, custom_id="volume_down", row=1)
    async def volume_down_btn(self, interaction: discord.Interaction, button: Button):
        """Уменьшить громкость"""
        current = self.cog.current.get(self.guild_id)
        if current:
            new_volume = max(current.volume - 0.1, 0.0)
            current.volume = new_volume
            await interaction.response.send_message(
                f"🔉 Громкость: {int(new_volume * 100)}%",
                ephemeral=True,
                delete_after=3
            )
            await self.cog.update_now_playing(self.guild_id)
        else:
            await interaction.response.send_message("❌ Ничего не играет", ephemeral=True, delete_after=3)


class Music(commands.Cog):
    """Основной музыкальный модуль с улучшенной стабильностью"""

    def __init__(self, bot):
        self.bot = bot
        # Состояние для каждой гильдии
        self.queues: Dict[int, List] = {}
        self.current: Dict[int, discord.PCMVolumeTransformer] = {}
        self.repeat_mode: Dict[int, str] = {}  # 'none', 'track', 'queue'
        self.shuffle_mode: Dict[int, bool] = {}  # Режим shuffle
        self.queue_locks: Dict[int, asyncio.Lock] = {}
        self.inactive_timers: Dict[int, asyncio.Task] = {}
        self.now_playing_messages: Dict[int, discord.Message] = {}

        logger.info("Music cog loaded with enhanced features")

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
            description=f"**[{current.title}]({current.webpage_url})**",
            color=ELLEN_COLOR
        )

        # Баннер Ellen Joe
        embed.set_author(name="EllenSings Music Bot", icon_url=ELLEN_AVATAR)

        # Thumbnail трека
        if current.thumbnail:
            embed.set_thumbnail(url=current.thumbnail)

        # Информация о треке
        duration = str(timedelta(seconds=current.duration)) if current.duration else "Live Stream"
        embed.add_field(name="👤 Автор", value=current.uploader, inline=True)
        embed.add_field(name="⏱️ Длительность", value=duration, inline=True)

        # Статус воспроизведения
        if voice_client.is_paused():
            status = "⏸️ Пауза"
        elif voice_client.is_playing():
            status = "▶️ Воспроизведение"
        else:
            status = "⏹️ Остановлено"

        embed.add_field(name="📻 Статус", value=status, inline=True)

        # Информация об очереди
        queue_len = len(self.get_queue(guild_id))
        next_track = self.get_queue(guild_id)[0] if queue_len > 0 else None

        if next_track:
            embed.add_field(
                name=f"📃 Следующий трек (из {queue_len})",
                value=f"{next_track.title[:80]}",
                inline=False
            )
        else:
            embed.add_field(name="📃 Очередь", value="Больше треков нет", inline=False)

        # Настройки внизу
        repeat = self.repeat_mode.get(guild_id, 'none')
        shuffle = self.shuffle_mode.get(guild_id, False)
        volume = int(current.volume * 100)

        repeat_icons = {'none': '➡️ Выкл', 'track': '🔂 Трек', 'queue': '🔁 Очередь'}
        shuffle_icon = "🔀 Вкл" if shuffle else "➡️ Выкл"

        embed.add_field(name="🔁 Повтор", value=repeat_icons[repeat], inline=True)
        embed.add_field(name="🔀 Shuffle", value=shuffle_icon, inline=True)
        embed.add_field(name="🔊 Громкость", value=f"{volume}%", inline=True)

        embed.set_footer(text="EllenSings • Используйте кнопки для управления", icon_url=ELLEN_AVATAR)

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

        # Defer сразу - Discord дает только 3 секунды на ответ
        await ctx.defer()

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
        try:
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)

            # Добавляем в очередь
            queue = self.get_queue(ctx.guild.id)
            was_empty = len(queue) == 0 and not self.current.get(ctx.guild.id)
            queue.append(player)

            # Создаём красивый embed подтверждения
            embed = discord.Embed(
                title="✅ Добавлено в очередь",
                description=f"**[{player.title}]({player.webpage_url})**",
                color=ELLEN_COLOR
            )

            embed.set_author(name="EllenSings Music Bot", icon_url=ELLEN_AVATAR)
            embed.set_thumbnail(url=player.thumbnail)

            # Детали трека
            duration = str(timedelta(seconds=player.duration)) if player.duration else "Live"
            embed.add_field(name="👤 Автор", value=player.uploader, inline=True)
            embed.add_field(name="⏱️ Длительность", value=duration, inline=True)
            embed.add_field(name="📍 Позиция", value=f"#{len(queue)}", inline=True)

            user_avatar = ctx.author.avatar.url if ctx.author.avatar else None
            embed.set_footer(text=f"Запросил {ctx.author.display_name}", icon_url=user_avatar)

            await ctx.send(embed=embed)

            # Запускаем обработку очереди
            await self.process_queue(ctx.guild.id)

            # АВТОМАТИЧЕСКИ показываем панель управления если трек начал играться
            if was_empty:
                await asyncio.sleep(1)  # Даём время начать воспроизведение
                current = self.current.get(ctx.guild.id)
                if current:
                    # Создаём панель управления
                    control_embed = discord.Embed(
                        title="🎧 Сейчас играет",
                        description=f"**[{current.title}]({current.webpage_url})**",
                        color=ELLEN_COLOR
                    )
                    control_embed.set_author(name="EllenSings Music Bot", icon_url=ELLEN_AVATAR)
                    control_embed.set_thumbnail(url=current.thumbnail)

                    duration_str = str(timedelta(seconds=current.duration)) if current.duration else "Live"
                    control_embed.add_field(name="👤 Автор", value=current.uploader, inline=True)
                    control_embed.add_field(name="⏱️ Длительность", value=duration_str, inline=True)
                    control_embed.add_field(name="📻 Статус", value="▶️ Воспроизведение", inline=True)

                    volume = int(current.volume * 100)
                    control_embed.add_field(name="🔊 Громкость", value=f"{volume}%", inline=True)
                    control_embed.set_footer(text="Используйте кнопки для управления", icon_url=ELLEN_AVATAR)

                    view = MusicControls(self, ctx.guild.id)
                    control_msg = await ctx.channel.send(embed=control_embed, view=view)
                    self.now_playing_messages[ctx.guild.id] = control_msg

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
            color=ELLEN_COLOR
        )
        await ctx.send(embed=embed)
        await self.update_now_playing(ctx.guild.id)

    @commands.hybrid_command(name="search", description="Поиск треков с интерактивным выбором")
    @app_commands.describe(query="Поисковый запрос")
    async def search(self, ctx: commands.Context, *, query: str):
        """Поиск треков YouTube с интерактивным меню выбора"""

        await ctx.defer()

        # Проверка голосового канала
        if not ctx.author.voice:
            embed = discord.Embed(
                title="❌ Ошибка",
                description="Вы должны находиться в голосовом канале",
                color=0xFF6B6B
            )
            return await ctx.send(embed=embed, ephemeral=True)

        # Подключаемся к каналу если ещё не подключены
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

        try:
            # Импортируем ytdl для поиска
            from utils.ytdl import ytdl

            # Поиск треков
            search_query = f"ytsearch10:{query}"
            data = await self.bot.loop.run_in_executor(
                None,
                lambda: ytdl.extract_info(search_query, download=False)
            )

            if not data or 'entries' not in data or not data['entries']:
                embed = discord.Embed(
                    title="❌ Ничего не найдено",
                    description=f"По запросу **{query}** ничего не найдено",
                    color=0xFF6B6B
                )
                return await ctx.send(embed=embed)

            # Фильтруем None результаты
            results = [entry for entry in data['entries'] if entry]

            if not results:
                embed = discord.Embed(
                    title="❌ Ничего не найдено",
                    description=f"По запросу **{query}** ничего не найдено",
                    color=0xFF6B6B
                )
                return await ctx.send(embed=embed)

            # Создаём embed с результатами
            embed = discord.Embed(
                title="🔍 Результаты поиска",
                description=f"Найдено **{len(results)}** треков по запросу: **{query}**\nВыберите трек из списка ниже",
                color=ELLEN_COLOR
            )

            embed.set_author(name="EllenSings Music Bot", icon_url=ELLEN_AVATAR)
            embed.set_footer(text="Выберите трек в течение 60 секунд", icon_url=ELLEN_AVATAR)

            # Показываем первые 5 результатов в preview
            preview_text = ""
            for i, result in enumerate(results[:5]):
                duration = str(timedelta(seconds=result.get('duration', 0))) if result.get('duration') else "Live"
                preview_text += f"`{i+1}.` **{result['title'][:60]}**\n"
                preview_text += f"    👤 {result.get('uploader', 'Unknown')[:40]} • ⏱️ {duration}\n"

            if len(results) > 5:
                preview_text += f"\n*...и ещё {len(results) - 5} треков*"

            embed.add_field(name="🎵 Превью результатов", value=preview_text, inline=False)

            # Создаём интерактивное меню
            view = SearchResultsView(self, ctx, results)
            await ctx.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error in search command: {e}")
            embed = discord.Embed(
                title="❌ Ошибка поиска",
                description=f"Не удалось выполнить поиск: {str(e)}",
                color=0xFF6B6B
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="playlist", description="Добавить плейлист в очередь")
    @app_commands.describe(url="URL плейлиста YouTube")
    async def playlist(self, ctx: commands.Context, *, url: str):
        """Добавить весь плейлист YouTube в очередь"""

        await ctx.defer()

        # Проверка голосового канала
        if not ctx.author.voice:
            embed = discord.Embed(
                title="❌ Ошибка",
                description="Вы должны находиться в голосовом канале",
                color=0xFF6B6B
            )
            return await ctx.send(embed=embed, ephemeral=True)

        # Подключаемся к каналу
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

        try:
            from utils.ytdl import ytdl

            # Загружаем инфо о плейлисте
            playlist_info = await self.bot.loop.run_in_executor(
                None,
                lambda: ytdl.extract_info(url, download=False, process=False)
            )

            if not playlist_info or 'entries' not in playlist_info:
                embed = discord.Embed(
                    title="❌ Ошибка",
                    description="Это не плейлист или плейлист недоступен",
                    color=0xFF6B6B
                )
                return await ctx.send(embed=embed)

            entries = [e for e in playlist_info['entries'] if e]

            if not entries:
                embed = discord.Embed(
                    title="❌ Пустой плейлист",
                    description="Плейлист не содержит доступных треков",
                    color=0xFF6B6B
                )
                return await ctx.send(embed=embed)

            # Уведомление о загрузке
            loading_embed = discord.Embed(
                title="⏳ Загрузка плейлиста...",
                description=f"Найдено **{len(entries)}** треков\nЗагрузка может занять некоторое время...",
                color=ELLEN_COLOR
            )
            loading_embed.set_author(name="EllenSings Music Bot", icon_url=ELLEN_AVATAR)
            loading_msg = await ctx.send(embed=loading_embed)

            # Загружаем треки
            queue = self.get_queue(ctx.guild.id)
            added = 0

            for i, entry in enumerate(entries[:50]):  # Лимит 50 треков
                try:
                    player = await YTDLSource.from_url(
                        entry.get('url') or entry.get('webpage_url'),
                        loop=self.bot.loop,
                        stream=True
                    )
                    queue.append(player)
                    added += 1

                    # Обновляем прогресс каждые 5 треков
                    if (i + 1) % 5 == 0:
                        loading_embed.description = f"Загружено {added}/{len(entries[:50])} треков..."
                        await loading_msg.edit(embed=loading_embed)

                except Exception as e:
                    logger.warning(f"Failed to load track from playlist: {e}")
                    continue

            # Финальное уведомление
            success_embed = discord.Embed(
                title="✅ Плейлист добавлен",
                description=f"**{added}** треков добавлено в очередь из плейлиста",
                color=ELLEN_COLOR
            )
            success_embed.set_author(name="EllenSings Music Bot", icon_url=ELLEN_AVATAR)
            success_embed.set_footer(text=f"Запросил {ctx.author.display_name}")

            await loading_msg.edit(embed=success_embed)

            # Запускаем воспроизведение
            await self.process_queue(ctx.guild.id)

        except Exception as e:
            logger.error(f"Error loading playlist: {e}")
            embed = discord.Embed(
                title="❌ Ошибка загрузки плейлиста",
                description=f"Не удалось загрузить плейлист: {str(e)}",
                color=0xFF6B6B
            )
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Music(bot))
