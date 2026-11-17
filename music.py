"""YouTube search and one sequential music player per Discord server."""

import asyncio
from collections import deque
from dataclasses import dataclass, replace
import json
import logging
import os
from pathlib import Path
import random
import re
import signal
import sys
import tempfile
import textwrap
from urllib.parse import parse_qs, urlparse

import discord
from discord import app_commands


logger = logging.getLogger("capri-anthem.music")
DENO = Path(__file__).parent / "bin/deno"
MAX_QUEUE = 100
PLAYBACK_PANEL_REFRESH_SECONDS = 10
HACK_CHANCE = 0.30
HACK_COOLDOWN_SECONDS = 15 * 60
HACK_STYLE_PATTERNS = {
    "remix": r"\b(?:remix|bootleg|mashup)\b",
    "lofi": r"\blo[\s-]?fi\b",
    "acoustic": r"\b(?:acoustic|bản mộc)\b",
    "cover": r"\bcover\b",
    "live": r"\b(?:live at|live from|live session|live version)\b|[\[(]\s*live\s*[\])]",
    "slowed": r"\b(?:slowed|slow\s*down)\b",
    "sped up": r"\b(?:sped\s*up|nightcore)\b",
    "instrumental": r"\b(?:instrumental|karaoke)\b",
    "soundtrack": r"\b(?:soundtrack|ost|original score|motion picture|film score|symphonic suite)\b",
    "edm": r"\b(?:edm|hardstyle|techno|trance|house|dubstep|drum and bass|phonk)\b",
    "compilation": r"\b(?:compilation|megamix|full album|playlist|continuous mix)\b|liên khúc",
}


class MusicError(Exception):
    pass


async def acknowledge_play(interaction):
    try:
        await interaction.response.defer()
    except discord.NotFound as error:
        if error.code != 10062:
            raise
        age = (discord.utils.utcnow() - interaction.created_at).total_seconds()
        logger.warning("Play acknowledgement expired at %.2fs; using channel response", age)


async def send_music_result(interaction, content, *, view=None, wait=False):
    options = {"allowed_mentions": discord.AllowedMentions.none()}
    if view is not None:
        options["view"] = view
    if interaction.response.is_done():
        try:
            return await interaction.followup.send(content, wait=wait, **options)
        except discord.NotFound as error:
            if error.code not in {10015, 10062}:
                raise
            logger.warning("Music interaction expired; using channel response")
    # A channel message remains usable after the original interaction expires.
    # Search menus produce fresh interactions when the user chooses a track.
    return await interaction.channel.send(content, **options)


async def confirm_queued(interaction, track):
    title = discord.utils.escape_markdown(track.title)
    try:
        await send_music_result(interaction, f"Đã thêm **{title}** vào hàng đợi.")
    except discord.HTTPException:
        logger.warning("Track queued but confirmation could not be sent in guild %s", interaction.guild_id,
                       exc_info=True)


def youtube_query(query):
    query = query.strip()
    if not query or len(query) > 200:
        raise MusicError("Nhập tên bài hoặc link YouTube, tối đa 200 ký tự.")
    if "://" not in query:
        return "ytsearch5:" + query
    parsed = urlparse(query)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"https", "http"}:
        raise MusicError("Hãy nhập tên bài hoặc link YouTube.")
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        parts = parsed.path.strip("/").split("/")
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
            video_id = parts[1]
    else:
        raise MusicError("Bản này hỗ trợ tên bài và link YouTube.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise MusicError("Hãy dùng link một video YouTube hoặc nhập tên bài.")
    return "https://www.youtube.com/watch?v=" + video_id


async def extract(query, *, search=False, destination=None):
    command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-warnings",
               "--no-playlist", "--socket-timeout", "15", "--retries", "1",
               "--js-runtimes", f"deno:{DENO}", "--force-ipv4"]
    if destination:
        command.extend(["--output", str(destination), "--no-part", "--no-progress",
                        "--match-filter", "!is_live", "--print", "after_move:filepath"])
    else:
        command.append("--dump-single-json")
    if search:
        command.append("--flat-playlist")
    else:
        command.extend(["--format", "bestaudio/best"])
    process = await asyncio.create_subprocess_exec(
        *command, "--", query, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=75)
    except (asyncio.CancelledError, TimeoutError):
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await process.wait()
        raise
    if process.returncode:
        # Signed media URLs and cookies stay out of Discord replies and logs.
        error = stderr.decode(errors="replace").lower()
        if "sign in" in error or "confirm you" in error:
            raise MusicError("YouTube đang yêu cầu xác minh cho kết nối này. Hãy thử bài khác.")
        raise MusicError("Chưa lấy được âm thanh YouTube. Hãy thử lại hoặc chọn bài khác.")
    if destination:
        path = stdout.decode().strip()
        if not path or not Path(path).is_file():
            raise MusicError("Chưa tải được bài. Livestream chưa được hỗ trợ.")
        return path
    return json.loads(stdout)


@dataclass
class Track:
    title: str
    url: str
    duration: int
    artist: str = ""
    surprise: bool = False
    requester_id: int | None = None
    earns_order_xp: bool = True
    credited_artist: str = ""

    @classmethod
    def from_info(cls, info):
        if not isinstance(info, dict):
            raise MusicError("Kết quả YouTube không hợp lệ.")
        video_id = str(info.get("id", ""))
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise MusicError("Kết quả YouTube không hợp lệ.")
        if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
            raise MusicError("Hãy chọn một bài đã đăng, livestream chưa được hỗ trợ.")
        return cls(str(info.get("title") or "Không có tiêu đề")[:200],
                   "https://www.youtube.com/watch?v=" + video_id,
                   int(info.get("duration") or 0),
                   str(info.get("artist") or info.get("channel") or info.get("uploader") or "")[:120],
                   credited_artist=str(info.get("artist") or "")[:120])

    @property
    def label(self):
        minutes, seconds = divmod(self.duration, 60)
        return f"{self.title} · {minutes}:{seconds:02d}"


def hack_artist(track):
    # An uploader can be a label or a channel that reposts unrelated artists.
    prefix = re.split(r"\s+[-–—]\s+", track.title, maxsplit=1)
    if track.credited_artist:
        artist = track.credited_artist
    elif re.search(r"\s+-\s+topic$", track.artist, re.IGNORECASE):
        artist = re.sub(r"\s+-\s+topic$", "", track.artist, flags=re.IGNORECASE)
    elif len(prefix) == 2:
        artist = prefix[0]
    else:
        return ""
    return " ".join(artist.casefold().split())


def hack_styles(track):
    return frozenset(style for style, pattern in HACK_STYLE_PATTERNS.items()
                     if re.search(pattern, track.title, re.IGNORECASE))


class Player:
    def __init__(self, guild, channel, music):
        self.guild = guild
        self.channel = channel
        self.music = music
        self.panel = None
        self.pending = deque()
        self.ready = asyncio.Event()
        self.current = None
        self.skip_requested = asyncio.Event()
        self.worker = None
        self.recent_tracks = deque(maxlen=6)
        self.next_hack_at = 0.0

    def add(self, track):
        if len(self.pending) >= MAX_QUEUE:
            raise MusicError("Hàng đợi đã đủ 100 bài.")
        self.pending.append(track)
        self.ready.set()
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self.run())

    async def announce(self, content=None, *, embed=None, view=None):
        try:
            return await self.channel.send(content, embed=embed, view=view,
                                           allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logger.warning("Cannot send music update in guild %s", self.guild.id)

    async def play(self, track):
        with tempfile.TemporaryDirectory(prefix="capri-anthem-") as folder:
            path = await extract(track.url, destination=Path(folder) / "audio.%(ext)s")
            await self.play_file(track, path)

    async def play_file(self, track, path):
        member = self.guild.me
        permissions_for = getattr(self.channel, "permissions_for", None)
        allow_embed = member is not None and permissions_for is not None and permissions_for(member).embed_links
        panel = PlaybackControls(self.music, self, track, allow_embed=allow_embed)
        self.panel = panel
        try:
            await self.play_once(path, panel, first_pass=True)
            while panel.looping and panel.active and not self.skip_requested.is_set():
                await self.play_once(path, panel, first_pass=False)
        finally:
            await panel.retire()
            self.panel = None

    async def play_once(self, path, panel, *, first_pass):
        voice = self.guild.voice_client
        if voice is None or not voice.is_connected():
            raise MusicError("Bot đã mất kết nối kênh thoại. Hãy dùng /play để kết nối lại.")
        source = discord.FFmpegPCMAudio(
            path, before_options="-nostdin", options="-vn -loglevel error",
        )
        source = discord.PCMVolumeTransformer(source, volume=0.35)
        finished = asyncio.get_running_loop().create_future()
        loop = asyncio.get_running_loop()
        levels = getattr(self.music.bot, "levels", None)
        hack_reward = first_pass and panel.track.surprise and levels is not None
        track_order = (first_pass and not panel.track.surprise
                       and panel.track.earns_order_xp and levels is not None)

        def complete(error):
            self.music.refresh_listeners(self.guild)
            if not finished.done():
                if error:
                    finished.set_exception(error)
                else:
                    listener = None
                    if track_order:
                        listener = levels.end_completion(
                            self.guild, completed=panel.active and not self.skip_requested.is_set()
                        )
                    finished.set_result(listener)

        try:
            voice.play(source, after=lambda error: loop.call_soon_threadsafe(complete, error))
            if track_order:
                levels.begin_completion(self.guild, panel.track.requester_id)
            self.music.refresh_listeners(self.guild)
            panel.elapsed = 0.0
            panel.running_since = loop.time()
            if first_pass:
                display = panel.display()
                panel.message = await self.announce(**display, view=panel)
                panel.last_display = display
            else:
                await panel.refresh()
            while panel.message and not finished.done():
                await asyncio.wait({finished}, timeout=PLAYBACK_PANEL_REFRESH_SECONDS)
                if not finished.done() and panel.active:
                    await panel.refresh()
            listener = await finished
            if hack_reward:
                await levels.finish_hack(self.guild, completed=panel.active and not self.skip_requested.is_set())
            if listener is not None:
                await levels.record_completion(self.guild.id, listener)
        finally:
            if track_order:
                levels.end_completion(self.guild)
            voice.stop()
            self.music.refresh_listeners(self.guild)
            source.cleanup()

    def hack_channel(self):
        voice = self.guild.voice_client
        if voice is None or not voice.is_connected() or voice.is_playing() or voice.is_paused():
            return None
        channel = voice.channel
        if channel and any(not member.bot and member.voice and not member.voice.deaf
                           and not member.voice.self_deaf for member in channel.members):
            return channel
        return None

    async def maybe_hack(self):
        loop = asyncio.get_running_loop()
        channel = self.hack_channel()
        if channel is None:
            return False
        if loop.time() < self.next_hack_at or random.random() >= HACK_CHANCE:
            return
        seeds = [track for track in self.recent_tracks if not track.surprise][-3:]
        if not seeds:
            return False
        seed = seeds[-1]
        artist = hack_artist(seed)
        if not artist:
            return False
        styles = hack_styles(seed)
        hint = " ".join((artist, *sorted(styles), "music"))
        try:
            results = await asyncio.wait_for(extract(f"ytsearch12:{hint}", search=True), timeout=12)
        except (MusicError, TimeoutError, ValueError, OSError):
            logger.info("Capri Hack search failed in guild %s", self.guild.id, exc_info=True)
            return
        if self.hack_channel() != channel:
            return
        known_tracks = [*self.recent_tracks, *self.pending]
        seen_urls = {track.url for track in known_tracks}
        seen_titles = {track.title.casefold() for track in known_tracks}
        candidates = []
        for entry in results.get("entries") or []:
            try:
                track = Track.from_info(entry)
            except (MusicError, TypeError, ValueError):
                continue
            if (track.url in seen_urls or track.title.casefold() in seen_titles
                    or not 45 <= track.duration <= 900 or hack_styles(track) != styles):
                continue
            if hack_artist(track) == artist:
                candidates.append(track)
        if candidates:
            recommendation = random.choice(candidates[:5])
            recommendation.surprise = True
            self.next_hack_at = loop.time() + HACK_COOLDOWN_SECONDS
            self.pending.appendleft(recommendation)
            self.ready.set()
            return True
        return False

    async def run(self):
        while True:
            await self.ready.wait()
            self.current = self.pending.popleft()
            if not self.pending:
                self.ready.clear()
            self.skip_requested.clear()
            operation = asyncio.create_task(self.play(self.current))
            skip_waiter = asyncio.create_task(self.skip_requested.wait())
            completed = None
            try:
                done, _ = await asyncio.wait({operation, skip_waiter}, return_when=asyncio.FIRST_COMPLETED)
                if operation in done and not self.skip_requested.is_set():
                    await operation
                    completed = self.current
            except MusicError as error:
                await self.announce(str(error))
            except TimeoutError:
                await self.announce("YouTube phản hồi quá lâu. Đang chuyển sang bài tiếp theo.")
            except Exception:
                logger.error("Playback failed in guild %s", self.guild.id)
                await self.announce("Phát bài thất bại. Đang chuyển sang bài tiếp theo.")
            finally:
                operation.cancel()
                skip_waiter.cancel()
                await asyncio.gather(operation, skip_waiter, return_exceptions=True)
                self.current = None
            if completed is not None:
                self.recent_tracks.append(completed)
                await self.maybe_hack()

    async def stop(self):
        if self.worker is not None:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None
        self.pending.clear()
        self.ready.clear()
        self.current = None
        if self.guild.voice_client:
            self.guild.voice_client.stop()
        self.music.refresh_listeners(self.guild)
        if self.panel:
            await self.panel.retire()
            self.panel = None


class PlaybackControls(discord.ui.View):
    def __init__(self, music, player, track, *, allow_embed=True):
        super().__init__(timeout=None)
        self.music = music
        self.player = player
        self.track = track
        self.message = None
        self.active = True
        self.looping = False
        self.allow_embed = allow_embed
        self.last_display = None
        self.elapsed = 0.0
        self.running_since = asyncio.get_running_loop().time()
        self.edit_lock = asyncio.Lock()

    @staticmethod
    def timestamp(seconds):
        minutes, seconds = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    def progress(self):
        elapsed = self.elapsed
        if self.running_since is not None:
            elapsed += asyncio.get_running_loop().time() - self.running_since
        duration = self.track.duration
        if duration > 0:
            elapsed = min(elapsed, duration)
            total = self.timestamp(duration)
            marker = int(8 * elapsed / duration)
            bar = "━" * marker + "●" + "─" * (8 - marker)
            return f"`{self.timestamp(elapsed)}  {bar}  {total}`"
        return f"`{self.timestamp(elapsed)}`"

    @property
    def status(self):
        if not self.active:
            return "Đã kết thúc"
        return "Đang tạm dừng" if self.running_since is None else "Đang phát"

    @staticmethod
    def display_text(value, limit):
        text = " ".join(value.split())
        if len(text) > limit:
            text = textwrap.shorten(text, width=limit, placeholder="…")
            if text == "…":
                text = value.lstrip()[:limit - 1] + "…"
        return discord.utils.escape_markdown(text)

    @property
    def title(self):
        return self.display_text(self.track.title, 62) or "Không có tiêu đề"

    def next_title(self):
        if self.active and not self.looping and self.player.pending:
            return self.display_text(self.player.pending[0].title, 42) or "Không có tiêu đề"
        return None

    def details(self):
        artist = self.display_text(self.track.artist, 30)
        if self.track.surprise:
            attribution = "⚡ Capri Hack · Capri đã chiếm sóng"
        elif self.track.requester_id is not None:
            attribution = " · ".join(filter(None, [artist, f"Yêu cầu bởi <@{self.track.requester_id}>"]))
        else:
            attribution = artist
        progress = self.progress()
        return f"{attribution}\n\n{progress}" if attribution else progress

    def content(self):
        message = f"**{self.status}**\n**{self.title}**\n{self.details()}"
        next_title = self.next_title()
        if self.active and self.looping:
            message += "\n\n**Lặp bài** · Đang bật"
        elif next_title:
            message += f"\n\n**Tiếp theo**\n{next_title}"
        return message

    def display(self):
        if not self.allow_embed:
            return {"content": self.content(), "embed": None}
        color = 0xFF2467
        if not self.active or self.running_since is None:
            color = 0x71677D
        elif self.track.surprise:
            color = 0x53FF82
        embed = discord.Embed(
            title=self.title,
            description=self.details(),
            color=color,
        )
        embed.set_author(name=self.status)
        video = re.fullmatch(r"https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})", self.track.url)
        if video:
            embed.set_thumbnail(url=f"https://i.ytimg.com/vi/{video[1]}/mqdefault.jpg")
        next_title = self.next_title()
        if self.active and self.looping:
            embed.add_field(name="Lặp bài", value="Đang bật", inline=False)
        elif next_title:
            embed.add_field(name="Tiếp theo", value=next_title, inline=False)
        return {"content": None, "embed": embed}

    async def refresh(self):
        voice = self.player.guild.voice_client
        paused = voice is not None and voice.is_paused()
        now = asyncio.get_running_loop().time()
        if (paused or not self.active) and self.running_since is not None:
            self.elapsed += now - self.running_since
            self.running_since = None
        elif self.active and not paused and self.running_since is None:
            self.running_since = now
        self.toggle.label = "Tiếp tục" if paused else "Tạm dừng"
        self.toggle.emoji = "▶️" if paused else "⏸️"
        self.repeat.label = "Tắt lặp" if self.looping and self.active else "Lặp bài"
        self.repeat.style = (discord.ButtonStyle.success if self.looping and self.active
                             else discord.ButtonStyle.secondary)
        if self.message:
            async with self.edit_lock:
                display = self.display()
                if display == self.last_display:
                    return
                try:
                    await self.message.edit(**display, view=self,
                                            allowed_mentions=discord.AllowedMentions.none())
                    self.last_display = display
                except discord.NotFound:
                    self.message = None
                except discord.HTTPException:
                    logger.warning("Cannot update playback panel in guild %s", self.player.guild.id)

    async def retire(self):
        if not self.active:
            return
        self.active = False
        for item in self.children:
            item.disabled = True
        self.stop()
        await self.refresh()

    @discord.ui.button(label="Tạm dừng", emoji="⏸️", style=discord.ButtonStyle.primary, row=0)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music.perform(interaction, "toggle", panel=self)

    @discord.ui.button(label="Bỏ bài", emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music.perform(interaction, "skip", panel=self)

    @discord.ui.button(label="Dừng", emoji="⏹️", style=discord.ButtonStyle.secondary, row=0)
    async def stop_playback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music.perform(interaction, "stop", panel=self)

    @discord.ui.button(label="Hàng đợi", emoji="📋", style=discord.ButtonStyle.secondary, row=1)
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music.perform(interaction, "queue", panel=self)

    @discord.ui.button(label="Lặp bài", emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def repeat(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music.perform(interaction, "repeat", panel=self)

    @discord.ui.button(label="Lưu vào playlist", emoji="➕", style=discord.ButtonStyle.secondary, row=1)
    async def save_track(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice, player = self.music.control(interaction)
        if not self.active or player is not self.player or player.current is not self.track:
            raise MusicError("Hãy dùng nút trên bài đang phát.")
        await interaction.response.send_modal(self.music.bot.playlists.save_modal(self.track))

    async def on_error(self, interaction, error, item):
        if isinstance(error, MusicError):
            message = str(error)
        else:
            logger.exception("Playback button failed in guild %s", interaction.guild_id)
            message = "Thao tác thất bại. Hãy thử lại hoặc dùng lệnh slash."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class SearchResults(discord.ui.View):
    def __init__(self, music, owner_id, tracks):
        super().__init__(timeout=90)
        self.music = music
        self.owner_id = owner_id
        self.tracks = tracks
        self.selected = False
        self.message = None
        self.menu = discord.ui.Select(placeholder="Chọn bài để thêm vào hàng đợi", options=[
            discord.SelectOption(label=track.title[:100], value=str(index),
                                 description=track.label[-100:])
            for index, track in enumerate(tracks)
        ])
        self.menu.callback = self.choose
        self.add_item(self.menu)

    def stop(self):
        self.music.views.discard(self)
        super().stop()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Hãy dùng /play để chọn bài của bạn.", ephemeral=True)
            return False
        return True

    async def choose(self, interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.music.bot.voice_lock:
            if self.selected:
                await interaction.followup.send("Bạn đã chọn bài từ danh sách này.", ephemeral=True)
                return
            try:
                track = self.tracks[int(self.menu.values[0])]
                await self.music.enqueue(interaction, track)
            except MusicError as error:
                await interaction.followup.send(str(error), ephemeral=True)
                return
            except Exception:
                logger.exception("Cannot queue selected track in guild %s", interaction.guild_id)
                await interaction.followup.send("Chưa thêm được bài. Hãy thử /play lại.", ephemeral=True)
                return
            self.selected = True
            self.menu.disabled = True
            self.stop()
        await confirm_queued(interaction, track)
        try:
            await interaction.edit_original_response(view=self)
        except discord.HTTPException:
            logger.warning("Could not disable selection menu in guild %s", interaction.guild_id)

    async def on_timeout(self):
        self.music.views.discard(self)
        self.menu.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Music:
    def __init__(self, bot, connect_voice):
        self.bot = bot
        self.connect_voice = connect_voice
        self.players = {}
        self.search_slots = asyncio.Semaphore(2)
        self.views = set()

    def refresh_listeners(self, guild):
        levels = getattr(self.bot, "levels", None)
        if levels:
            levels.refresh(guild)

    def player(self, interaction):
        player = self.players.get(interaction.guild_id)
        if player is None:
            player = Player(interaction.guild, interaction.channel, self)
            self.players[interaction.guild_id] = player
        return player

    async def enqueue(self, interaction, track):
        await self.enqueue_tracks(interaction, [track])

    async def enqueue_tracks(self, interaction, tracks):
        player = self.player(interaction)
        if len(player.pending) >= MAX_QUEUE:
            raise MusicError("Hàng đợi đã đủ 100 bài.")
        voice = await self.connect_voice(interaction)
        if voice is None:
            raise MusicError("Hãy vào cùng kênh thoại với bot rồi chọn lại.")
        if voice.is_playing() and player.current is None:
            raise MusicError("Bot đang phát âm thử, hãy đợi 3 giây.")
        player.channel = interaction.channel
        accepted = tracks[:MAX_QUEUE - len(player.pending)]
        if not accepted:
            raise MusicError("Hàng đợi đã đủ 100 bài.")
        for track in accepted:
            player.add(replace(track, requester_id=interaction.user.id))
        levels = getattr(self.bot, "levels", None)
        counted_orders = sum(track.earns_order_xp and not track.surprise for track in accepted)
        if levels and counted_orders:
            await levels.record_order(interaction.guild_id, interaction.user.id, counted_orders)
        return len(accepted)

    async def stop_guild(self, guild_id):
        player = self.players.pop(guild_id, None)
        if player:
            await player.stop()

    async def close(self):
        for view in tuple(self.views):
            view.stop()
        for guild_id in list(self.players):
            await self.stop_guild(guild_id)

    def queue_text(self, guild_id):
        player = self.players.get(guild_id)
        if player is None:
            return "Hàng đợi đang trống."
        tracks = list(player.pending)
        current = discord.utils.escape_markdown(player.current.label) if player.current else "Chưa phát"
        lines = ["**Hiện tại** " + current]
        lines.extend(f"{index}. {discord.utils.escape_markdown(track.label[:90])}"
                     for index, track in enumerate(tracks[:15], 1))
        if len(tracks) > 15:
            lines.append(f"Còn {len(tracks) - 15} bài phía sau.")
        return "\n".join(lines)[:1950]

    async def perform(self, interaction, action, *, panel=None):
        await interaction.response.defer(ephemeral=panel is not None, thinking=True)
        async with self.bot.voice_lock:
            voice, player = self.control(interaction)
            if panel and (not panel.active or player is not panel.player or player.current is not panel.track):
                raise MusicError("Bài này đã kết thúc. Hãy dùng nút ở bài đang phát.")
            if action == "toggle":
                action = "resume" if voice.is_paused() else "pause"
            if action == "queue":
                message = self.queue_text(interaction.guild_id)
            elif action == "repeat":
                panel.looping = not panel.looping
                await panel.refresh()
                message = ("Đã bật lặp bài hiện tại." if panel.looping
                           else "Đã tắt lặp. Bài hiện tại sẽ phát đến hết.")
            elif action == "pause":
                if not voice.is_playing():
                    raise MusicError("Hiện chưa có âm thanh đang phát.")
                voice.pause()
                self.refresh_listeners(interaction.guild)
                message = "Đã tạm dừng."
                if player and player.panel:
                    await player.panel.refresh()
            elif action == "resume":
                if not voice.is_paused():
                    raise MusicError("Hiện chưa có bài đang tạm dừng.")
                voice.resume()
                self.refresh_listeners(interaction.guild)
                message = "Đang tiếp tục phát."
                if player and player.panel:
                    await player.panel.refresh()
            elif action == "skip":
                if player is None or player.current is None:
                    raise MusicError("Hiện chưa có bài để bỏ qua.")
                player.skip_requested.set()
                if player.panel:
                    await player.panel.retire()
                message = "Đã yêu cầu bỏ qua bài."
            elif action == "stop":
                await self.stop_guild(interaction.guild_id)
                voice.stop()
                message = "Đã dừng nhạc và xóa hàng đợi. Dùng /leave để rời kênh."
            else:
                raise ValueError(f"Unknown playback action: {action}")
        await interaction.followup.send(message, ephemeral=panel is not None,
                                        allowed_mentions=discord.AllowedMentions.none())

    def install(self):
        tree = self.bot.tree

        @tree.command(name="random", description="Chọn ngẫu nhiên 1–10 bài YouTube theo từ khóa")
        @app_commands.guild_only()
        @app_commands.describe(keyword="Thể loại, nghệ sĩ hoặc chủ đề nhạc",
                               count="Số bài muốn thêm, từ 1 đến 10")
        async def random_music(interaction: discord.Interaction, keyword: str,
                               count: app_commands.Range[int, 1, 10] = 5):
            await acknowledge_play(interaction)
            if interaction.user.voice is None:
                raise MusicError("Bạn hãy vào kênh thoại trước.")
            keyword = keyword.strip()
            if not keyword or len(keyword) > 200 or "://" in keyword:
                raise MusicError("Nhập từ khóa nhạc từ 1 đến 200 ký tự, ví dụ lofi hoặc remix.")
            async with self.search_slots:
                info = await extract("ytsearch30:" + keyword, search=True)
            candidates = {}
            for entry in info.get("entries") or []:
                try:
                    track = Track.from_info(entry)
                except (MusicError, TypeError, ValueError):
                    continue
                candidates.setdefault(track.url, replace(track, earns_order_xp=False))
            if not candidates:
                raise MusicError("Không tìm được bài cho từ khóa này. Hãy thử từ khóa khác.")
            tracks = random.sample(list(candidates.values()), min(count, len(candidates)))
            async with self.bot.voice_lock:
                accepted = await self.enqueue_tracks(interaction, tracks)
            lines = [f"Đã thêm **{accepted}/{count} bài ngẫu nhiên** theo từ khóa "
                     f"**{discord.utils.escape_markdown(keyword)}**.",
                     "Các bài này chỉ cộng XP nghe theo thời gian, không cộng XP order hoặc thưởng nghe hết."]
            lines.extend(f"{i}. {discord.utils.escape_markdown(t.title[:120])}"
                         for i, t in enumerate(tracks[:accepted], 1))
            await send_music_result(interaction, "\n".join(lines))

        @tree.command(name="play", description="Tìm nhạc YouTube theo tên hoặc phát link một bài")
        @app_commands.guild_only()
        @app_commands.describe(query="Tên bài, nghệ sĩ hoặc link YouTube")
        async def play(interaction: discord.Interaction, query: str):
            await acknowledge_play(interaction)
            if interaction.user.voice is None:
                raise MusicError("Bạn hãy vào kênh thoại trước.")
            target = youtube_query(query)
            async with self.search_slots:
                info = await extract(target, search=True)
            entries = info.get("entries") if target.startswith("ytsearch") else [info]
            tracks = []
            for entry in entries or []:
                try:
                    tracks.append(Track.from_info(entry))
                except (MusicError, TypeError):
                    continue
            if not tracks:
                raise MusicError("Không tìm được bài phù hợp. Hãy thử tên bài kèm nghệ sĩ.")
            if not target.startswith("ytsearch"):
                async with self.bot.voice_lock:
                    await self.enqueue(interaction, tracks[0])
                await confirm_queued(interaction, tracks[0])
                return
            view = SearchResults(self, interaction.user.id, tracks[:5])
            # Drop expired views without retaining every past search.
            self.views = {item for item in self.views if not item.is_finished()}
            self.views.add(view)
            view.message = await send_music_result(interaction, "Chọn bài bạn muốn nghe trong 90 giây.", view=view, wait=True)

        @tree.command(name="queue", description="Xem bài hiện tại và hàng đợi")
        @app_commands.guild_only()
        async def queue(interaction: discord.Interaction):
            await interaction.response.send_message(self.queue_text(interaction.guild_id),
                                                    allowed_mentions=discord.AllowedMentions.none())

        @tree.command(name="pause", description="Tạm dừng bài đang phát")
        @app_commands.guild_only()
        async def pause(interaction: discord.Interaction):
            await self.perform(interaction, "pause")

        @tree.command(name="resume", description="Tiếp tục phát bài đã tạm dừng")
        @app_commands.guild_only()
        async def resume(interaction: discord.Interaction):
            await self.perform(interaction, "resume")

        @tree.command(name="skip", description="Bỏ qua bài đang phát hoặc đang tải")
        @app_commands.guild_only()
        async def skip(interaction: discord.Interaction):
            await self.perform(interaction, "skip")

        @tree.command(name="stop", description="Dừng nhạc và xóa hàng đợi")
        @app_commands.guild_only()
        async def stop(interaction: discord.Interaction):
            await self.perform(interaction, "stop")

    def control(self, interaction):
        voice = interaction.guild.voice_client
        member_voice = interaction.user.voice
        if voice is None or not voice.is_connected():
            raise MusicError("Bot chưa kết nối kênh thoại.")
        if member_voice is None or member_voice.channel.id != voice.channel.id:
            raise MusicError("Bạn hãy vào cùng kênh thoại với bot.")
        return voice, self.players.get(interaction.guild_id)
