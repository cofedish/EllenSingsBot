"""
Music Cog для Discord бота EllenSings
Управление музыкальной очередью, воспроизведением и UI
🎵 Ellen Joe Theme - минималистичный, стильный дизайн
"""
import asyncio
import logging
import random
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Select, View

from utils.ytdl import YTDLSource, validate_query, ytdl, ytdl_playlist

logger = logging.getLogger('music')

# Ellen Joe брендинг
ELLEN_COLOR = 0x5BCEFA  # Голубой Ellen
ELLEN_AVATAR = "https://preview.redd.it/ellen-joe-fixing-her-hair-by-v0-42mc2jm3elcd1.jpeg?width=1080&crop=smart&auto=webp&s=1a898cd6856ed7bd23c556abd3854d92a2c37ef4"  # Ellen Joe аватар
ELLEN_BANNER = "https://i.imgur.com/3kZw7xM.png"  # Ellen Joe баннер


def same_voice_channel():
    """Check: команды управления доступны только из voice-канала, где сидит бот"""
    async def predicate(ctx: commands.Context) -> bool:
        vc = ctx.guild.voice_client if ctx.guild else None
        if not vc or not vc.is_connected():
            raise commands.CheckFailure('Бот сейчас не в голосовом канале')
        author_voice = getattr(ctx.author, 'voice', None)
        if not author_voice or author_voice.channel != vc.channel:
            raise commands.CheckFailure(
                'Управлять воспроизведением могут только участники голосового канала бота'
            )
        return True
    return commands.check(predicate)


def member_can_control(interaction: discord.Interaction) -> bool:
    """Проверка для кнопок: пользователь находится в том же voice-канале, что и бот"""
    guild = interaction.guild
    vc = guild.voice_client if guild else None
    member_voice = getattr(interaction.user, 'voice', None)
    return bool(vc and vc.is_connected() and member_voice and member_voice.channel == vc.channel)


async def deny_control(interaction: discord.Interaction):
    """Ответ пользователю, которому недоступно управление"""
    await interaction.response.send_message(
        '❌ Управлять могут только участники голосового канала бота',
        ephemeral=True,
        delete_after=5
    )


class QueuePaginator(View):
    """Пагинация для отображения очереди треков"""
    def __init__(self, cog, guild_id: int, page: int = 0):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.page = page

    def get_queue_embed(self) -> discord.Embed:
        """Создаёт ПРЕМИУМ embed с очередью треков"""
        queue = self.cog.get_queue(self.guild_id)
        track_info = self.cog.current_track_info.get(self.guild_id)

        # Премиум стиль Ellen Joe
        embed = discord.Embed(
            title="",
            description="## 🎵 Очередь воспроизведения",
            color=ELLEN_COLOR
        )

        # Баннер Ellen Joe
        embed.set_author(
            name="EllenSings Music Bot",
            icon_url="https://i.imgur.com/EllenJoe.png"
        )

        # Текущий трек с деталями
        if track_info:
            duration = str(timedelta(seconds=track_info.duration)) if track_info.duration else "🔴 Live"
            current_text = f"╔═══════════════════════════════╗\n"
            current_text += f"║ **[{track_info.title[:45]}]({track_info.webpage_url})**\n"
            current_text += f"║\n"
            current_text += f"║ 👤 {track_info.uploader[:40]}\n"
            current_text += f"║ ⏱️ {duration}\n"
            current_text += f"╚═══════════════════════════════╝"

            embed.add_field(
                name="▶️ Сейчас играет",
                value=current_text,
                inline=False
            )

            # Большая картинка текущего трека
            if track_info.thumbnail:
                embed.set_image(url=track_info.thumbnail)

        # Следующие треки с пагинацией
        items_per_page = 6
        start = self.page * items_per_page
        end = start + items_per_page
        page_queue = queue[start:end]

        if page_queue:
            queue_text = "╔═══════════════════════════════╗\n"
            for i, track in enumerate(page_queue):
                duration = str(timedelta(seconds=track.duration)) if track.duration else "🔴 Live"
                queue_text += f"║ `{start + i + 1}.` **{track.title[:40]}**\n"
                queue_text += f"║     ⏱️ {duration} • 👤 {track.uploader[:25]}\n"
                if i < len(page_queue) - 1:
                    queue_text += f"║\n"
            queue_text += f"╚═══════════════════════════════╝"

            max_page = (len(queue) - 1) // items_per_page + 1 if queue else 1

            embed.add_field(
                name=f"📃 Следующие треки (Всего: {len(queue)} | Страница {self.page + 1}/{max_page})",
                value=queue_text,
                inline=False
            )
        elif not track_info:
            embed.description += "\n\n*Очередь пуста. Добавьте треки командой `/play` или `/search`*"

        # Информация внизу
        repeat_mode = self.cog.repeat_mode.get(self.guild_id, 'none')
        shuffle_status = "🔀 Вкл" if self.cog.shuffle_mode.get(self.guild_id) else "➡️ Выкл"
        repeat_icons = {'none': '➡️ Выкл', 'track': '🔂 Трек', 'queue': '🔁 Очередь'}

        embed.set_footer(
            text=f"Повтор: {repeat_icons[repeat_mode]} • Shuffle: {shuffle_status}",
            icon_url="https://i.imgur.com/EllenJoe.png"
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
        items_per_page = 6
        max_page = (len(queue) - 1) // items_per_page if queue else 0
        if self.page < max_page:
            self.page += 1
            await interaction.response.edit_message(embed=self.get_queue_embed(), view=self)
        else:
            await interaction.response.defer()


class SearchResultsView(View):
    """Интерфейс выбора из результатов поиска"""
    def __init__(self, cog, ctx, results: list[dict]):
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
        if not member_can_control(interaction):
            return await deny_control(interaction)

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
            was_empty = len(queue) == 0 and not self.cog.current.get(self.ctx.guild.id)
            queue.append(player)

            # Запускаем воспроизведение
            await self.cog.process_queue(self.ctx.guild.id)

            # Если трек начал играть сразу - показываем панель управления
            if was_empty:
                await asyncio.sleep(0.5)
                track_info = self.cog.current_track_info.get(self.ctx.guild.id)
                if track_info:
                    await self.cog.update_now_playing(self.ctx.guild.id, channel=self.ctx.channel, force_new=True)
            else:
                # Если трек добавлен в очередь - показываем уведомление
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

                # Обновляем карточку "Сейчас играет"
                await self.cog.update_now_playing(self.ctx.guild.id)

        except Exception as e:
            logger.error(f"Error adding track from search: {e}")
            await interaction.followup.send(f"❌ Ошибка: {e!s}", ephemeral=True)


class MusicControls(View):
    """Кнопки управления воспроизведением в стиле Ellen Joe"""
    def __init__(self, cog, guild_id: int):
        # timeout=None создаёт persistent view, но тогда кнопки надо регистрировать
        # через bot.add_view() после перезапуска — иначе "Interaction failed".
        # Ставим 600 сек: если бот перезапустится, старые сообщения просто протухнут.
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id

        # Определяем стили кнопок в зависимости от состояния
        repeat_mode = cog.repeat_mode.get(guild_id, 'none')
        shuffle_active = cog.shuffle_mode.get(guild_id, False)

        # Создаём кнопки динамически с правильными стилями
        self.add_item(Button(
            emoji="⏯️",
            style=discord.ButtonStyle.primary,
            custom_id=f"play_pause_{guild_id}",
            row=0
        ))
        self.add_item(Button(
            emoji="⏭️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"skip_{guild_id}",
            row=0
        ))
        self.add_item(Button(
            emoji="⏹️",
            style=discord.ButtonStyle.danger,
            custom_id=f"stop_{guild_id}",
            row=0
        ))
        self.add_item(Button(
            emoji="🔁",
            style=discord.ButtonStyle.success if repeat_mode != 'none' else discord.ButtonStyle.secondary,
            label="Repeat" if repeat_mode != 'none' else None,
            custom_id=f"repeat_{guild_id}",
            row=0
        ))
        self.add_item(Button(
            emoji="🔀",
            style=discord.ButtonStyle.success if shuffle_active else discord.ButtonStyle.secondary,
            label="Shuffle" if shuffle_active else None,
            custom_id=f"shuffle_{guild_id}",
            row=0
        ))
        self.add_item(Button(
            emoji="📃",
            style=discord.ButtonStyle.secondary,
            custom_id=f"queue_{guild_id}",
            row=1
        ))
        self.add_item(Button(
            emoji="🔊",
            style=discord.ButtonStyle.secondary,
            custom_id=f"volume_up_{guild_id}",
            row=1
        ))
        self.add_item(Button(
            emoji="🔉",
            style=discord.ButtonStyle.secondary,
            custom_id=f"volume_down_{guild_id}",
            row=1
        ))

        # Привязываем callbacks
        for item in self.children:
            if "play_pause" in item.custom_id:
                item.callback = self.play_pause_callback
            elif "skip" in item.custom_id:
                item.callback = self.skip_callback
            elif "stop" in item.custom_id:
                item.callback = self.stop_callback
            elif "repeat" in item.custom_id:
                item.callback = self.repeat_callback
            elif "shuffle" in item.custom_id:
                item.callback = self.shuffle_callback
            elif "queue" in item.custom_id:
                item.callback = self.queue_callback
            elif "volume_up" in item.custom_id:
                item.callback = self.volume_up_callback
            elif "volume_down" in item.custom_id:
                item.callback = self.volume_down_callback

    async def play_pause_callback(self, interaction: discord.Interaction):
        """Пауза/Возобновление"""
        if not member_can_control(interaction):
            return await deny_control(interaction)
        await self.cog.toggle_play_pause(self.guild_id)
        await interaction.response.defer()
        await self.cog.update_now_playing(self.guild_id)

    async def skip_callback(self, interaction: discord.Interaction):
        """Пропуск трека"""
        if not member_can_control(interaction):
            return await deny_control(interaction)
        guild = self.cog.bot.get_guild(self.guild_id)
        if guild and guild.voice_client:
            guild.voice_client.stop()
            await interaction.response.send_message("⏭️ Трек пропущен", ephemeral=True, delete_after=3)
        else:
            await interaction.response.send_message("❌ Ничего не играет", ephemeral=True, delete_after=3)

    async def stop_callback(self, interaction: discord.Interaction):
        """Остановка и очистка"""
        if not member_can_control(interaction):
            return await deny_control(interaction)
        await self.cog.stop_playback(self.guild_id)
        await interaction.response.send_message("⏹️ Воспроизведение остановлено", ephemeral=True, delete_after=3)

    async def repeat_callback(self, interaction: discord.Interaction):
        """Переключение режима повтора"""
        if not member_can_control(interaction):
            return await deny_control(interaction)
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

    async def shuffle_callback(self, interaction: discord.Interaction):
        """Перемешать очередь"""
        if not member_can_control(interaction):
            return await deny_control(interaction)
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

    async def queue_callback(self, interaction: discord.Interaction):
        """Показать очередь"""
        paginator = QueuePaginator(self.cog, self.guild_id)
        await interaction.response.send_message(
            embed=paginator.get_queue_embed(),
            view=paginator,
            ephemeral=True
        )

    async def volume_up_callback(self, interaction: discord.Interaction):
        """Увеличить громкость"""
        if not member_can_control(interaction):
            return await deny_control(interaction)
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

    async def volume_down_callback(self, interaction: discord.Interaction):
        """Уменьшить громкость"""
        if not member_can_control(interaction):
            return await deny_control(interaction)
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

    async def on_timeout(self):
        """Отключаем кнопки после истечения таймаута"""
        for item in self.children:
            item.disabled = True
        # Пытаемся обновить сообщение с отключёнными кнопками
        msg = self.cog.now_playing_messages.get(self.guild_id)
        if msg:
            try:
                await msg.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


class TrackInfo:
    """Класс для хранения информации о треке (для повтора)"""
    def __init__(self, url: str, title: str, uploader: str, duration: int, thumbnail: str, webpage_url: str, repeat_mode: str = 'none'):
        self.url = url
        self.title = title
        self.uploader = uploader
        self.duration = duration
        self.thumbnail = thumbnail
        self.webpage_url = webpage_url
        self.repeat_mode_on_start = repeat_mode  # Режим повтора, когда трек начал играть


class Music(commands.Cog):
    """Основной музыкальный модуль с улучшенной стабильностью"""

    def __init__(self, bot):
        self.bot = bot
        # Состояние для каждой гильдии
        self.queues: dict[int, list] = {}
        self.current: dict[int, discord.PCMVolumeTransformer] = {}
        self.current_track_info: dict[int, TrackInfo] = {}  # Информация о текущем треке для повтора
        self.repeat_mode: dict[int, str] = {}  # 'none', 'track', 'queue'
        self.shuffle_mode: dict[int, bool] = {}  # Режим shuffle
        self.queue_locks: dict[int, asyncio.Lock] = {}
        self.inactive_timers: dict[int, asyncio.Task] = {}
        self.now_playing_messages: dict[int, discord.Message] = {}

        logger.info("Music cog loaded with enhanced features")

    def get_queue(self, guild_id: int) -> list:
        """Получить очередь для гильдии"""
        return self.queues.setdefault(guild_id, [])

    def get_lock(self, guild_id: int) -> asyncio.Lock:
        """Получить lock для очереди гильдии"""
        if guild_id not in self.queue_locks:
            self.queue_locks[guild_id] = asyncio.Lock()
        return self.queue_locks[guild_id]

    async def ensure_voice(self, ctx: commands.Context):
        """
        Проверяет, что автор в голосовом канале, и подключает бота к нему.

        Returns:
            VoiceClient или None, если подключиться не удалось
            (сообщение об ошибке уже отправлено).

        Raises:
            commands.CheckFailure: автор не в voice-канале или бот занят в другом.
        """
        author_voice = getattr(ctx.author, 'voice', None)
        if not author_voice or not author_voice.channel:
            raise commands.CheckFailure('Вы должны находиться в голосовом канале')

        vc = ctx.voice_client
        if vc and vc.is_connected():
            if vc.channel != author_voice.channel:
                raise commands.CheckFailure('Бот уже играет в другом голосовом канале')
            return vc

        try:
            vc = await author_voice.channel.connect()
            logger.info(f"Connected to voice channel in guild {ctx.guild.id}")
            return vc
        except Exception as e:
            logger.error(f"Failed to connect to voice: {e}")
            embed = discord.Embed(
                title="❌ Ошибка подключения",
                description="Не удалось подключиться к голосовому каналу",
                color=0xFF6B6B
            )
            await ctx.send(embed=embed)
            return None

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Следим за voice-каналом: авто-выход из пустого канала, чистка при кике"""
        guild = member.guild

        # Бота отключили от канала (kick/disconnect) — чистим состояние
        if member.id == self.bot.user.id and before.channel is not None and after.channel is None:
            logger.info(f"Bot disconnected from voice in guild {guild.id}, cleaning up")
            await self._cleanup_state(guild.id)
            return

        vc = guild.voice_client
        if not vc or not vc.channel:
            return

        humans = [m for m in vc.channel.members if not m.bot]
        if not humans:
            # Все слушатели вышли — отключаемся через 2 минуты
            logger.info(f"Voice channel empty in guild {guild.id}, starting leave timer")
            self.start_inactivity_timer(guild.id, delay=120)
        elif vc.is_playing() or vc.is_paused():
            # Слушатели вернулись и музыка играет — таймер не нужен
            self.cancel_inactivity_timer(guild.id)

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

            # Отменяем таймер, если он был.
            # Но не тогда, когда в канале нет слушателей: иначе бот с включённым
            # повтором будет вечно играть в пустом канале.
            humans = [m for m in voice_client.channel.members if not m.bot]
            if humans:
                self.cancel_inactivity_timer(guild_id)

            # Берём следующий трек
            player = queue.pop(0)
            self.current[guild_id] = player

            # Сохраняем информацию о треке для повтора (включая текущий режим повтора)
            current_repeat_mode = self.repeat_mode.get(guild_id, 'none')
            self.current_track_info[guild_id] = TrackInfo(
                url=player.data.get('url'),
                title=player.title,
                uploader=player.uploader,
                duration=player.duration,
                thumbnail=player.thumbnail,
                webpage_url=player.webpage_url,
                repeat_mode=current_repeat_mode
            )

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

            # Обновляем панель Now Playing (создаём новую при смене трека)
            await self.update_now_playing(guild_id, force_new=True)

    async def handle_track_end(self, guild_id: int):
        """
        Обработка окончания трека с учётом режима повтора.
        Использует режим повтора, который был активен когда трек НАЧАЛ играть,
        а не текущий глобальный режим. Это предотвращает неожиданное поведение
        при изменении режима повтора во время воспроизведения.
        """
        track_info = self.current_track_info.get(guild_id)

        # Обработка режима повтора (используем режим, который был при старте трека)
        if track_info:
            repeat = track_info.repeat_mode_on_start
            queue = self.get_queue(guild_id)

            if repeat == 'track':
                # Повтор текущего трека - но только если нет других треков в очереди
                # Это предотвращает блокировку очереди повторяющимся треком
                if len(queue) == 0:
                    try:
                        player = await YTDLSource.from_url(
                            track_info.webpage_url,
                            loop=self.bot.loop,
                            stream=True
                        )
                        queue.insert(0, player)
                        logger.info(f"Track repeat: {track_info.title}")
                    except Exception as e:
                        logger.error(f"Failed to repeat track: {e}")
                else:
                    logger.info(f"Skipping track repeat because queue has {len(queue)} tracks waiting")
            elif repeat == 'queue':
                # Повтор очереди - ПЕРЕСОЗДАЕМ player и добавляем в конец
                try:
                    player = await YTDLSource.from_url(
                        track_info.webpage_url,
                        loop=self.bot.loop,
                        stream=True
                    )
                    queue.append(player)
                    logger.info(f"Track added to queue repeat: {track_info.title}")
                except Exception as e:
                    logger.error(f"Failed to add track to queue: {e}")

        # Обрабатываем следующий трек
        await self.process_queue(guild_id)

    def start_inactivity_timer(self, guild_id: int, delay: int = 600):
        """Запускает таймер на отключение при неактивности (по умолчанию 10 минут)"""
        self.cancel_inactivity_timer(guild_id)

        async def timer():
            try:
                await asyncio.sleep(delay)
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
        if guild and guild.voice_client:
            guild.voice_client.stop()
            await guild.voice_client.disconnect()

        await self._cleanup_state(guild_id)

    async def _cleanup_state(self, guild_id: int):
        """Сбрасывает состояние гильдии: очередь, режимы, таймеры, панель управления"""
        self.queues.pop(guild_id, None)
        self.current.pop(guild_id, None)
        self.current_track_info.pop(guild_id, None)
        self.repeat_mode.pop(guild_id, None)
        self.shuffle_mode.pop(guild_id, None)
        self.cancel_inactivity_timer(guild_id)

        msg = self.now_playing_messages.pop(guild_id, None)
        if msg:
            try:
                await msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass

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

    async def update_now_playing(self, guild_id: int, channel=None, force_new=False):
        """Обновляет/создаёт embed с текущим треком"""
        track_info = self.current_track_info.get(guild_id)
        current = self.current.get(guild_id)

        if not track_info or not current:
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        voice_client = guild.voice_client
        if not voice_client:
            return

        # Создаём ПРЕМИУМ embed в стиле Ellen Joe
        embed = discord.Embed(
            title="",
            description=f"## 🎧 Сейчас играет\n### **[{track_info.title[:60]}]({track_info.webpage_url})**",
            color=ELLEN_COLOR
        )

        # Баннер Ellen Joe
        embed.set_author(
            name="EllenSings Music Bot",
            icon_url=ELLEN_AVATAR
        )

        # Картинка трека (большая)
        if track_info.thumbnail:
            embed.set_image(url=track_info.thumbnail)

        # Информация о треке с красивыми разделителями
        duration = str(timedelta(seconds=track_info.duration)) if track_info.duration else "🔴 Live"

        info_text = f"```\n"
        info_text += f"╔═══════════════════════════════╗\n"
        info_text += f"║ 👤 Автор: {track_info.uploader[:24]}\n"
        info_text += f"║ ⏱️  Длительность: {duration}\n"

        # Статус воспроизведения
        if voice_client.is_paused():
            status = "⏸️  Пауза"
        elif voice_client.is_playing():
            status = "▶️  Воспроизведение"
        else:
            status = "⏹️  Остановлено"

        info_text += f"║ 📻 Статус: {status}\n"
        info_text += f"╚═══════════════════════════════╝\n"
        info_text += f"```"

        embed.add_field(name="", value=info_text, inline=False)

        # Информация об очереди
        queue_len = len(self.get_queue(guild_id))
        next_track = self.get_queue(guild_id)[0] if queue_len > 0 else None

        queue_text = f"```\n"
        queue_text += f"╔═══════════════════════════════╗\n"
        if next_track:
            queue_text += f"║ Следующий: {next_track.title[:18]}\n"
            queue_text += f"║ 📃 Всего: {queue_len} треков\n"
        else:
            queue_text += f"║ Больше треков нет\n"
        queue_text += f"╚═══════════════════════════════╝\n"
        queue_text += f"```"

        embed.add_field(name="📃 Очередь", value=queue_text, inline=False)

        # Настройки с красивыми иконками и индикаторами
        repeat = self.repeat_mode.get(guild_id, 'none')
        shuffle = self.shuffle_mode.get(guild_id, False)
        volume = int(current.volume * 100)

        repeat_icons = {'none': '⚪ Выкл', 'track': '🟢 Трек', 'queue': '🟢 Очередь'}
        shuffle_icon = "🟢 Вкл" if shuffle else "⚪ Выкл"

        settings_text = f"```\n"
        settings_text += f"╔═══════════════════════════════╗\n"
        settings_text += f"║ 🔁 Повтор: {repeat_icons[repeat]}\n"
        settings_text += f"║ 🔀 Shuffle: {shuffle_icon}\n"
        settings_text += f"║ 🔊 Громкость: {volume}%\n"
        settings_text += f"╚═══════════════════════════════╝\n"
        settings_text += f"```"

        embed.add_field(name="⚙️ Настройки", value=settings_text, inline=False)

        # Ellen Joe thumbnail в углу
        embed.set_thumbnail(url=ELLEN_AVATAR)

        embed.set_footer(
            text="EllenSings • Premium Music Bot • Используйте кнопки для управления",
            icon_url=ELLEN_AVATAR
        )

        # Обновляем View с актуальным состоянием кнопок
        view = MusicControls(self, guild_id)

        # РЕДАКТИРУЕМ существующее сообщение или создаём новое
        if guild_id in self.now_playing_messages and not force_new:
            try:
                await self.now_playing_messages[guild_id].edit(embed=embed, view=view)
                return
            except (discord.NotFound, discord.HTTPException):
                del self.now_playing_messages[guild_id]

        # Создаём новое сообщение (если старого нет или force_new=True)
        if channel is None:
            # Находим канал из старого сообщения
            old_msg = self.now_playing_messages.get(guild_id)
            if old_msg:
                channel = old_msg.channel
                # Удаляем старое сообщение
                try:
                    await old_msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
            else:
                # Первый текстовый канал, куда бот реально может писать
                channel = next(
                    (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                    None
                )

        if channel:
            try:
                message = await channel.send(embed=embed, view=view)
                self.now_playing_messages[guild_id] = message
            except discord.HTTPException as e:
                logger.error(f"Failed to send now playing message: {e}")

    # ========== КОМАНДЫ ==========

    @commands.hybrid_command(name="play", description="Включить музыку")
    @app_commands.describe(query="Название трека или URL")
    async def play(self, ctx: commands.Context, *, query: str):
        """Добавить трек в очередь и начать воспроизведение"""

        # Defer сразу - Discord дает только 3 секунды на ответ
        await ctx.defer()

        # Проверка voice-канала автора и подключение
        voice_client = await self.ensure_voice(ctx)
        if voice_client is None:
            return

        # Загрузка трека
        try:
            player = await YTDLSource.from_url(query, loop=self.bot.loop, stream=True)

            # Добавляем в очередь
            queue = self.get_queue(ctx.guild.id)
            was_empty = len(queue) == 0 and not self.current.get(ctx.guild.id)
            queue.append(player)

            # Запускаем обработку очереди СРАЗУ
            await self.process_queue(ctx.guild.id)

            # Если трек начал играть сразу - показываем только панель управления
            if was_empty:
                await asyncio.sleep(0.5)  # Даём время начать воспроизведение
                track_info = self.current_track_info.get(ctx.guild.id)
                if track_info:
                    # Показываем панель управления вместо сообщения "добавлено"
                    await self.update_now_playing(ctx.guild.id, channel=ctx.channel, force_new=True)
            else:
                # Если трек добавлен в очередь (не играет сразу) - показываем уведомление
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

                # Обновляем существующую карточку "Сейчас играет" с новым количеством треков
                await self.update_now_playing(ctx.guild.id)

        except Exception as e:
            logger.error(f"Error loading track: {e}")
            embed = discord.Embed(
                title="❌ Ошибка загрузки",
                description=f"Не удалось загрузить трек: {e!s}",
                color=0xFF6B6B
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="skip", description="Пропустить текущий трек")
    @same_voice_channel()
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
    @same_voice_channel()
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
    @same_voice_channel()
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
    @same_voice_channel()
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
        track_info = self.current_track_info.get(ctx.guild.id)

        if not track_info:
            embed = discord.Embed(
                title="❌ Ничего не играет",
                description="Добавьте треки командой `/play` или `/search`",
                color=0xFF6B6B
            )
            return await ctx.send(embed=embed, ephemeral=True)

        # Используем update_now_playing для создания панели
        await self.update_now_playing(ctx.guild.id, channel=ctx.channel)

    @commands.hybrid_command(name="clear", description="Очистить очередь")
    @same_voice_channel()
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
    @same_voice_channel()
    async def repeat(self, ctx: commands.Context, mode: str | None = None):
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

        # Проверка voice-канала автора и подключение
        voice_client = await self.ensure_voice(ctx)
        if voice_client is None:
            return

        try:
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
                description=f"Не удалось выполнить поиск: {e!s}",
                color=0xFF6B6B
            )
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="playlist", description="Добавить плейлист в очередь")
    @app_commands.describe(url="URL плейлиста YouTube")
    async def playlist(self, ctx: commands.Context, *, url: str):
        """Добавить весь плейлист YouTube в очередь"""

        await ctx.defer()

        # Разрешаем только http(s)-ссылки
        url = validate_query(url)

        # Проверка voice-канала автора и подключение
        voice_client = await self.ensure_voice(ctx)
        if voice_client is None:
            return

        try:
            # Загружаем инфо о плейлисте (отдельный инстанс с включёнными плейлистами)
            playlist_info = await self.bot.loop.run_in_executor(
                None,
                lambda: ytdl_playlist.extract_info(url, download=False, process=False)
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

            queue = self.get_queue(ctx.guild.id)
            was_empty = len(queue) == 0 and not self.current.get(ctx.guild.id)
            total = min(len(entries), 50)

            # ЗАГРУЖАЕМ ПЕРВЫЙ ТРЕК СРАЗУ И НАЧИНАЕМ ИГРАТЬ
            try:
                first_player = await YTDLSource.from_url(
                    entries[0].get('url') or entries[0].get('webpage_url'),
                    loop=self.bot.loop,
                    stream=True
                )
                queue.append(first_player)

                # Запускаем воспроизведение первого трека
                await self.process_queue(ctx.guild.id)

                # Показываем панель управления сразу
                if was_empty:
                    await asyncio.sleep(0.5)
                    await self.update_now_playing(ctx.guild.id, channel=ctx.channel, force_new=True)

                added = 1
            except Exception as e:
                logger.error(f"Failed to load first track: {e}")
                embed = discord.Embed(
                    title="❌ Ошибка",
                    description=f"Не удалось загрузить первый трек плейлиста: {e!s}",
                    color=0xFF6B6B
                )
                return await ctx.send(embed=embed)

            # Уведомление о фоновой загрузке остальных треков
            if total > 1:
                loading_embed = discord.Embed(
                    title="⏳ Загрузка плейлиста в фоне...",
                    description=f"Первый трек начал играть!\nОстальные **{total - 1}** треков загружаются...",
                    color=ELLEN_COLOR
                )
                loading_embed.set_author(name="EllenSings Music Bot", icon_url=ELLEN_AVATAR)
                loading_msg = await ctx.send(embed=loading_embed)

                # ЗАГРУЖАЕМ ОСТАЛЬНЫЕ ТРЕКИ В ФОНЕ
                for i, entry in enumerate(entries[1:total], start=1):  # Пропускаем первый
                    try:
                        player = await YTDLSource.from_url(
                            entry.get('url') or entry.get('webpage_url'),
                            loop=self.bot.loop,
                            stream=True
                        )
                        queue.append(player)
                        added += 1

                        # Обновляем прогресс каждые 3 трека
                        if (i + 1) % 3 == 0 or i == total - 1:
                            progress = (added / total) * 100
                            filled = int(progress / 5)
                            empty = 20 - filled
                            progress_bar = f"{'▓' * filled}{'░' * empty}"

                            loading_embed.description = (
                                f"╔═══════════════════════════════╗\n"
                                f"║ Загрузка плейлиста...\n"
                                f"║\n"
                                f"║ {progress_bar}\n"
                                f"║ **{added}/{total}** треков ({int(progress)}%)\n"
                                f"╚═══════════════════════════════╝"
                            )
                            await loading_msg.edit(embed=loading_embed)

                    except Exception as e:
                        logger.warning(f"Failed to load track from playlist: {e}")
                        continue

                # Финальное уведомление
                success_embed = discord.Embed(
                    title="",
                    description=f"## ✅ Плейлист загружен\n╔═══════════════════════════════╗\n║ **{added}** треков в очереди\n╚═══════════════════════════════╝",
                    color=ELLEN_COLOR
                )
                success_embed.set_author(name="EllenSings Music Bot", icon_url=ELLEN_AVATAR)
                success_embed.set_footer(
                    text=f"Запросил {ctx.author.display_name}",
                    icon_url=ctx.author.avatar.url if ctx.author.avatar else None
                )
                await loading_msg.edit(embed=success_embed)

        except Exception as e:
            logger.error(f"Error loading playlist: {e}")
            embed = discord.Embed(
                title="❌ Ошибка загрузки плейлиста",
                description=f"Не удалось загрузить плейлист: {e!s}",
                color=0xFF6B6B
            )
            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Music(bot))
