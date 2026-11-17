"""Listening time accounting and persistent, per-server music ranks."""

import asyncio
from collections import defaultdict
from contextlib import closing
import logging
from io import BytesIO
from math import isqrt
from pathlib import Path
import sqlite3
import time

import discord
from discord import app_commands
from leaderboard_card import render_leaderboard
from rank_card import listening_time, render_rank_card, render_and_release
from rank_titles import TITLES, equipped_title


logger = logging.getLogger("capri-anthem.levels")
LISTENING_MS_PER_XP = 6000
XP_PER_ORDER = 2
XP_PER_COMPLETION = 5
XP_PER_HACK = 200
FIRST_LEVEL_XP = 25
LEVEL_STEP_XP = 5
RANKING_QUERY = """
    WITH activity AS (
        SELECT user_id, milliseconds, 0 AS orders, 0 AS completions, 0 AS bonus
        FROM listening WHERE guild_id = :guild AND milliseconds > 0
        UNION ALL
        SELECT user_id, 0, total, 0, 0
        FROM song_orders WHERE guild_id = :guild AND total > 0
        UNION ALL
        SELECT user_id, 0, 0, total, 0
        FROM completed_orders WHERE guild_id = :guild AND total > 0
        UNION ALL
        SELECT user_id, 0, 0, 0, xp FROM hack_rewards WHERE guild_id = :guild AND xp > 0
    ), totals AS (
        SELECT user_id, SUM(milliseconds) AS milliseconds, SUM(orders) AS orders,
               SUM(completions) AS completions, SUM(bonus) AS bonus
        FROM activity GROUP BY user_id
    ), ranked AS (
        SELECT user_id, milliseconds, orders, completions, bonus,
               ROW_NUMBER() OVER (
                   ORDER BY milliseconds / :listening_ms_per_xp + orders * :xp_per_order
                            + completions * :xp_per_completion + bonus DESC,
                            milliseconds DESC, user_id
               ) AS position
        FROM totals
    )
"""


def level_threshold(level):
    return FIRST_LEVEL_XP * level + LEVEL_STEP_XP * level * (level - 1) // 2


def rank_values(milliseconds, orders=0, completions=0, bonus=0):
    xp = milliseconds // LISTENING_MS_PER_XP + orders * XP_PER_ORDER + completions * XP_PER_COMPLETION + bonus
    # Invert the cumulative XP formula using integer arithmetic at each threshold.
    offset = 2 * FIRST_LEVEL_XP - LEVEL_STEP_XP
    level = (isqrt(offset ** 2 + 8 * LEVEL_STEP_XP * xp) - offset) // (2 * LEVEL_STEP_XP)
    return xp, level, level_threshold(level + 1)


class OwnRankView(discord.ui.View):
    def __init__(self, levels, owner_id, guild_id, profile):
        super().__init__(timeout=300)
        self.levels = levels
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.profile = profile

    async def interaction_check(self, interaction):
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("Dùng /rank để đổi danh hiệu của bạn.", ephemeral=True)
        return False


class RankTitleButton(OwnRankView):
    def __init__(self, levels, owner_id, guild_id, profile, can_equip=True):
        super().__init__(levels, owner_id, guild_id, profile)
        self.change.disabled = not can_equip or profile["level"] < TITLES[0].level

    @discord.ui.button(label="Đổi danh hiệu", style=discord.ButtonStyle.secondary)
    async def change(self, interaction, button):
        await interaction.response.send_message(
            "Chọn một danh hiệu để xem trước khung.",
            view=RankTitleMenu(self.levels, self.owner_id, self.guild_id, self.profile),
            ephemeral=True,
        )


class RankFrameGallery(OwnRankView):
    def __init__(self, levels, owner_id, guild_id, profile):
        super().__init__(levels, owner_id, guild_id, profile)
        self.index = 0
        self.lock = asyncio.Lock()
        self.choose.options = [discord.SelectOption(label=t.name, value=t.key,
                               description=f"Mở khóa ở cấp {t.level}") for t in TITLES]
        self.update_controls()

    def caption(self):
        title = TITLES[self.index]
        status = "Đã mở khóa" if self.profile["level"] >= title.level else f"Còn {title.level - self.profile['level']} cấp"
        return (f"**{title.name}** · Khung {self.index + 1}/{len(TITLES)}\n"
                f"Điều kiện mở khóa **cấp {title.level}** · Tổng **{level_threshold(title.level):,} XP**\n"
                f"{self.profile['name']} — {status}")

    def update_controls(self):
        self.previous.disabled = self.index == 0
        self.next_frame.disabled = self.index == len(TITLES) - 1
        for option in self.choose.options:
            option.default = option.value == TITLES[self.index].key

    async def show(self, interaction, *, key=None, step=0):
        await interaction.response.defer()
        async with self.lock:
            if self.is_finished():
                return
            self.index = (next(i for i, t in enumerate(TITLES) if t.key == key)
                          if key else max(0, min(len(TITLES) - 1, self.index + step)))
            self.update_controls()
            file = await self.levels.profile_file(self.profile, TITLES[self.index])
            await interaction.edit_original_response(content=self.caption(), attachments=[file], view=self)

    @discord.ui.select(placeholder="Xem khung của từng danh hiệu", row=0)
    async def choose(self, interaction, menu):
        await self.show(interaction, key=menu.values[0])

    @discord.ui.button(label="Trước", emoji="◀️", row=1)
    async def previous(self, interaction, button):
        await self.show(interaction, step=-1)

    @discord.ui.button(label="Sau", emoji="▶️", row=1)
    async def next_frame(self, interaction, button):
        await self.show(interaction, step=1)


class RankTitleMenu(OwnRankView):
    def __init__(self, levels, owner_id, guild_id, profile):
        super().__init__(levels, owner_id, guild_id, profile)
        self.unlocked = {title.key: title for title in TITLES if title.level <= profile["level"]}
        self.previewed = None
        self.lock = asyncio.Lock()
        self.choose.options = [discord.SelectOption(label="Tự động", value="auto",
                                                   description="Dùng danh hiệu cao nhất đã mở")]
        self.choose.options.extend(discord.SelectOption(label=title.name, value=title.key,
                                                        description=f"Mở ở cấp {title.level}")
                                   for title in self.unlocked.values())

    @discord.ui.select(placeholder="Danh hiệu đã sở hữu", row=0)
    async def choose(self, interaction, menu):
        value = menu.values[0]
        if value != "auto" and value not in self.unlocked:
            await interaction.response.send_message("Bạn chưa mở danh hiệu đó.", ephemeral=True)
            return
        await interaction.response.defer()
        async with self.lock:
            if self.is_finished():
                return
            title = equipped_title(self.profile["level"], value)
            attachment = await self.levels.profile_file(self.profile, title)
            self.previewed = value
            self.equip.disabled = False
            for option in menu.options:
                option.default = option.value == value
            label = f"{title.name} (tự động)" if value == "auto" else title.name
            await interaction.edit_original_response(content=f"Xem trước **{label}**",
                                                     attachments=[attachment], view=self)

    @discord.ui.button(label="Trang bị", style=discord.ButtonStyle.primary, row=1, disabled=True)
    async def equip(self, interaction, button):
        await interaction.response.defer()
        async with self.lock:
            if self.previewed is None or self.is_finished():
                return
            selection = None if self.previewed == "auto" else self.previewed
            await asyncio.to_thread(self.levels.save_title, self.guild_id, self.owner_id, selection)
            title = equipped_title(self.profile["level"], selection)
            label = f"{title.name} (tự động)" if selection is None else title.name
            await interaction.edit_original_response(
                content=f"Đã trang bị **{label}**. Dùng /rank để xem thẻ mới.", view=None
            )
            self.stop()


class ListeningLevels:
    def __init__(self, bot, music, path=None, clock=time.monotonic):
        self.bot = bot
        self.music = music
        self.path = Path(path) if path else Path.home() / ".local/state/capri-anthem/levels.sqlite3"
        self.clock = clock
        self.sessions = {}
        self.completion_listeners = {}
        self.pending = defaultdict(int)
        self.db_lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.worker = None
        self.closing = False
        self.render_slot = asyncio.Semaphore(1)

    def eligible(self, guild):
        voice = guild.voice_client
        player = self.music.players.get(guild.id)
        if voice is None or not voice.is_playing() or player is None or player.current is None:
            return set()
        return self.audience(guild)

    def audience(self, guild):
        voice = guild.voice_client
        if (self.closing or not self.bot.is_ready() or guild.unavailable
                or voice is None or not voice.is_connected() or voice.channel is None):
            return set()
        return {
            member.id for member in voice.channel.members
            if not member.bot and member.voice is not None
            and not member.voice.self_deaf and not member.voice.deaf
        }

    def begin_completion(self, guild, requester_id):
        if requester_id is not None and requester_id in self.audience(guild):
            self.completion_listeners[guild.id] = requester_id

    def end_completion(self, guild, *, completed=False):
        requester_id = self.completion_listeners.pop(guild.id, None)
        if completed and requester_id is not None and requester_id in self.audience(guild):
            return requester_id
        return None

    def refresh(self, guild, *, disconnected=False):
        now = int(self.clock() * 1000)
        listeners = set() if disconnected else self.eligible(guild)
        requester_id = self.completion_listeners.get(guild.id)
        if requester_id is not None and (disconnected or requester_id not in self.audience(guild)):
            self.completion_listeners.pop(guild.id, None)
        previous = [key for key in self.sessions if key[0] == guild.id]
        for key in previous:
            self.pending[key] += max(0, now - self.sessions.pop(key))
        for user_id in listeners:
            self.sessions[guild.id, user_id] = now

    def refresh_all(self, *, disconnected=False):
        for guild in self.bot.guilds:
            self.refresh(guild, disconnected=disconnected)

    def create_database(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS hack_rewards (
                    guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                    xp INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS listening (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    milliseconds INTEGER NOT NULL DEFAULT 0 CHECK(milliseconds >= 0),
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS listening_ranking
                ON listening (guild_id, milliseconds DESC, user_id)
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS song_orders (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS completed_orders (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS rank_titles (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    title_key TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)

    def write_hack_rewards(self, guild_id, listeners):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executemany("""
                INSERT INTO hack_rewards (guild_id, user_id, xp) VALUES (?, ?, ?)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET xp = xp + excluded.xp
            """, [(guild_id, user_id, XP_PER_HACK) for user_id in listeners])

    async def finish_hack(self, guild, *, completed):
        listeners = self.audience(guild) if completed else set()
        if completed and listeners:
            async with self.db_lock:
                task = asyncio.create_task(asyncio.to_thread(self.write_hack_rewards, guild.id, listeners))
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise

    def increment_orders(self, guild_id, user_id, count=1):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""
                INSERT INTO song_orders (guild_id, user_id, total) VALUES (?, ?, ?)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET total = song_orders.total + excluded.total
            """, (guild_id, user_id, count))

    async def record_order(self, guild_id, user_id, count=1):
        async with self.db_lock:
            try:
                await asyncio.to_thread(self.increment_orders, guild_id, user_id, count)
            except sqlite3.Error:
                logger.exception("Could not record song order in guild %s", guild_id)

    def increment_completions(self, guild_id, user_id):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""
                INSERT INTO completed_orders (guild_id, user_id, total) VALUES (?, ?, 1)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET total = total + 1
            """, (guild_id, user_id))

    async def record_completion(self, guild_id, user_id):
        async with self.db_lock:
            try:
                await asyncio.to_thread(self.increment_completions, guild_id, user_id)
            except sqlite3.Error:
                logger.exception("Could not record completed song in guild %s", guild_id)

    def write_batch(self, snapshot):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executemany("""
                INSERT INTO listening (guild_id, user_id, milliseconds) VALUES (?, ?, ?)
                ON CONFLICT (guild_id, user_id) DO UPDATE
                SET milliseconds = listening.milliseconds + excluded.milliseconds
            """, [(guild_id, user_id, amount) for (guild_id, user_id), amount in snapshot.items()])

    async def flush(self):
        async with self.db_lock:
            snapshot = {key: value for key, value in self.pending.items() if value > 0}
            if not snapshot:
                return
            # Finish an in-flight commit before acknowledging cancellation, so
            # the same listening interval cannot be written twice on retry.
            task = asyncio.create_task(asyncio.to_thread(self.write_batch, snapshot))
            cancelled = False
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
                await task
            for key, amount in snapshot.items():
                self.pending[key] -= amount
                if self.pending[key] == 0:
                    del self.pending[key]
            if cancelled:
                raise asyncio.CancelledError

    async def run(self):
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=60)
            except TimeoutError:
                self.refresh_all()
                try:
                    await self.flush()
                except sqlite3.Error:
                    logger.exception("Cannot save listening time; retaining pending XP for retry")

    async def start(self):
        if self.worker is None:
            await asyncio.to_thread(self.create_database)
            self.worker = asyncio.create_task(self.run())

    async def close(self):
        if self.worker is None:
            return
        self.closing = True
        self.refresh_all(disconnected=True)
        self.stop_event.set()
        await self.worker
        await self.flush()
        self.worker = None

    def read_rank(self, guild_id, user_id):
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(RANKING_QUERY + """
                SELECT milliseconds, position, orders, completions, bonus FROM ranked WHERE user_id = :user
            """, {"guild": guild_id, "user": user_id, "listening_ms_per_xp": LISTENING_MS_PER_XP,
                  "xp_per_order": XP_PER_ORDER, "xp_per_completion": XP_PER_COMPLETION}).fetchone()
            return row if row is not None else (0, None, 0, 0, 0)

    def read_leaderboard(self, guild_id):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(RANKING_QUERY + """
                SELECT user_id, milliseconds, orders, completions, bonus FROM ranked ORDER BY position LIMIT 10
            """, {"guild": guild_id, "listening_ms_per_xp": LISTENING_MS_PER_XP,
                  "xp_per_order": XP_PER_ORDER, "xp_per_completion": XP_PER_COMPLETION}).fetchall()

    def read_titles(self, guild_id, user_ids):
        parameters = ", ".join("?" for _ in user_ids)
        with closing(sqlite3.connect(self.path)) as connection:
            return dict(connection.execute(
                f"SELECT user_id, title_key FROM rank_titles WHERE guild_id = ? AND user_id IN ({parameters})",
                (guild_id, *user_ids),
            ))

    def save_title(self, guild_id, user_id, key):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            if key is None:
                connection.execute("DELETE FROM rank_titles WHERE guild_id = ? AND user_id = ?",
                                   (guild_id, user_id))
            else:
                connection.execute("""
                    INSERT INTO rank_titles (guild_id, user_id, title_key) VALUES (?, ?, ?)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET title_key = excluded.title_key
                """, (guild_id, user_id, key))

    async def profile_file(self, profile, title):
        async with self.render_slot:
            card = await asyncio.to_thread(render_and_release, render_rank_card, **profile, title=title)
        description = f'{profile["name"]}, cấp {profile["level"]}, {profile["xp"]} XP'
        if title:
            description += f", {title.name}"
        return discord.File(BytesIO(card), filename="capri-rank.png", description=description[:1024])

    async def rank_profile(self, interaction, member):
        self.refresh_all()
        await self.flush()
        milliseconds, position, orders, completions, bonus = await asyncio.to_thread(
            self.read_rank, interaction.guild_id, member.id
        )
        xp, level, next_xp = rank_values(milliseconds, orders, completions, bonus)
        selections = await asyncio.to_thread(self.read_titles, interaction.guild_id, [member.id])
        title = equipped_title(level, selections.get(member.id))
        avatar = None
        try:
            avatar = await asyncio.wait_for(member.display_avatar.replace(size=128, format="png").read(), timeout=5)
        except (discord.HTTPException, TimeoutError):
            logger.warning("Cannot load rank avatar for user %s", member.id)
        profile = dict(name=member.display_name, server=interaction.guild.name, avatar=avatar,
                       milliseconds=milliseconds, position=position, xp=xp, level=level,
                       base_xp=level_threshold(level), next_xp=next_xp, orders=orders,
                       earning=(interaction.guild_id, member.id) in self.sessions)
        return profile, title

    def install(self):
        @self.bot.tree.command(name="rank", description="Xem cấp, XP và thời gian nghe nhạc cùng Capri")
        @app_commands.guild_only()
        @app_commands.describe(member="Người muốn xem cấp, để trống để xem bản thân")
        async def rank(interaction: discord.Interaction, member: discord.Member | None = None):
            await interaction.response.defer()
            member = member or interaction.user
            profile, title = await self.rank_profile(interaction, member)
            file = await self.profile_file(profile, title)
            options = {}
            options["view"] = RankTitleButton(self, interaction.user.id, interaction.guild_id, profile,
                                             can_equip=member.id == interaction.user.id)
            await interaction.followup.send(file=file, allowed_mentions=discord.AllowedMentions.none(), **options)

        @self.bot.tree.command(name="frames", description="Xem tất cả khung danh hiệu và điều kiện mở khóa")
        @app_commands.guild_only()
        async def frames(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            profile, _ = await self.rank_profile(interaction, interaction.user)
            view = RankFrameGallery(self, interaction.user.id, interaction.guild_id, profile)
            await interaction.followup.send(content=view.caption(),
                                            file=await self.profile_file(profile, TITLES[0]),
                                            view=view, ephemeral=True)

        @self.bot.tree.command(name="leaderboard", description="Top 10 người nghe nhạc cùng Capri trong server")
        @app_commands.guild_only()
        async def leaderboard(interaction: discord.Interaction):
            await interaction.response.defer()
            self.refresh_all()
            await self.flush()
            rows = await asyncio.to_thread(self.read_leaderboard, interaction.guild_id)
            mentions = discord.AllowedMentions.none()
            if not rows:
                await interaction.followup.send(
                    "Bảng xếp hạng chưa có người nghe. Dùng **/play** để bắt đầu tích XP.",
                    allowed_mentions=mentions,
                )
                return

            async def display_name(user_id):
                member = interaction.guild.get_member(user_id)
                if member is None:
                    try:
                        member = await asyncio.wait_for(interaction.guild.fetch_member(user_id), timeout=3)
                    except (discord.HTTPException, TimeoutError):
                        # A former member can still have a listening record.
                        return f"ID {user_id}"
                return member.display_name

            user_ids = [row[0] for row in rows]
            selections = await asyncio.to_thread(self.read_titles, interaction.guild_id, user_ids)
            names = await asyncio.gather(*(display_name(user_id) for user_id in user_ids))
            chart = []
            summary = ["Bảng xếp hạng nghe nhạc"]
            for position, (name, (user_id, milliseconds, orders, completions, bonus)) in enumerate(zip(names, rows), 1):
                xp, level, _ = rank_values(milliseconds, orders, completions, bonus)
                title = equipped_title(level, selections.get(user_id))
                chart.append((name, milliseconds, xp, level, title))
                title_text = f"{title.name}, " if title else ""
                summary.append(f"Hạng {position}, {name}, {title_text}cấp {level}, {xp} XP, "
                               f"{listening_time(milliseconds)}.")
            async with self.render_slot:
                image = await asyncio.to_thread(render_and_release, render_leaderboard, interaction.guild.name, chart)
            await interaction.followup.send(
                file=discord.File(BytesIO(image), filename="capri-leaderboard.png",
                                  description="\n".join(summary)[:1024]),
                allowed_mentions=mentions,
            )
