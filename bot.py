import asyncio
from dataclasses import dataclass
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import signal

import discord
from discord import app_commands
from music import Music, MusicError, send_music_result
from levels import ListeningLevels
from playlists import Playlists
from help_ui import install_help


TOKEN_FILE = Path.home() / ".config/capri-anthem/token"
logger = logging.getLogger("capri-anthem")
EMPTY_TIMEOUT = 60
IDLE_TIMEOUT = 600
VOICE_CHECK_INTERVAL = 5


@dataclass
class VoiceIdleState:
    voice: discord.VoiceClient
    notice_channel: discord.abc.Messageable | None = None
    channel_id: int | None = None
    empty_since: float | None = None
    idle_since: float | None = None

    def check(self, now, player):
        channel = self.voice.channel
        if channel.id != self.channel_id:
            self.channel_id = channel.id
            self.empty_since = self.idle_since = None

        if any(not member.bot for member in channel.members):
            self.empty_since = None
        elif self.empty_since is None:
            self.empty_since = now

        if (self.voice.is_playing() or self.voice.is_paused()
                or (player and (player.current is not None or player.pending))):
            self.idle_since = None
        elif self.idle_since is None:
            self.idle_since = now

        if self.empty_since is not None and now - self.empty_since >= EMPTY_TIMEOUT:
            return "kênh thoại đã không có người trong 1 phút"
        if self.idle_since is not None and now - self.idle_since >= IDLE_TIMEOUT:
            return "đã 10 phút không phát nhạc và hàng đợi trống"
        return None


class Anthem(discord.Client):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        # Commands and controls keep their own message references.
        super().__init__(intents=intents, max_messages=None)
        self.tree = app_commands.CommandTree(self)
        self.synced_guilds = set()
        self.voice_lock = asyncio.Lock()
        self.voice_idle = {}
        self.voice_monitor = None

    async def setup_hook(self):
        await asyncio.to_thread(self.playlists.initialize)
        await self.levels.start()
        self.voice_monitor = asyncio.create_task(self.monitor_voice())

    def idle_state(self, voice):
        state = self.voice_idle.get(voice.guild.id)
        if state is None or state.voice is not voice:
            state = self.voice_idle[voice.guild.id] = VoiceIdleState(voice)
        return state

    async def monitor_voice(self):
        await self.wait_until_ready()
        loop = asyncio.get_running_loop()
        while True:
            for guild_id, state in list(self.voice_idle.items()):
                if state.voice.guild.voice_client is not state.voice:
                    self.voice_idle.pop(guild_id, None)
            for voice in self.voice_clients:
                if not voice.is_connected() or voice.channel is None:
                    continue
                state = self.idle_state(voice)
                player = music.players.get(voice.guild.id)
                if not state.check(loop.time(), player):
                    continue
                try:
                    await self.leave_if_idle(state)
                except (discord.DiscordException, OSError):
                    logger.warning("Auto-leave failed in guild %s", voice.guild.id, exc_info=True)
            await asyncio.sleep(VOICE_CHECK_INTERVAL)

    async def leave_if_idle(self, state):
        voice = state.voice
        guild = voice.guild
        async with self.voice_lock:
            if guild.voice_client is not voice or not voice.is_connected() or voice.channel is None:
                return
            player = music.players.get(guild.id)
            reason = state.check(asyncio.get_running_loop().time(), player)
            if not reason:
                return
            channel = state.notice_channel or voice.channel
            await music.stop_guild(guild.id)
            await voice.disconnect(force=True)
            self.voice_idle.pop(guild.id, None)

        try:
            await channel.send(f"Capri Anthem đã tự rời kênh thoại vì {reason}.",
                               allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logger.warning("Could not send auto-leave notice in guild %s", guild.id)

    async def sync_guild(self, guild):
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self.synced_guilds.add(guild.id)

    async def on_ready(self):
        for guild in self.guilds:
            if guild.id not in self.synced_guilds:
                await self.sync_guild(guild)
        logger.info("Online as %s in %s server(s)", self.user, len(self.guilds))
        self.levels.refresh_all()

    async def on_disconnect(self):
        self.levels.refresh_all(disconnected=True)

    async def on_resumed(self):
        self.levels.refresh_all()

    async def on_guild_join(self, guild):
        await self.sync_guild(guild)

    async def on_guild_remove(self, guild):
        self.levels.refresh(guild, disconnected=True)
        await music.stop_guild(guild.id)

    async def close(self):
        if self.voice_monitor is not None:
            self.voice_monitor.cancel()
            await asyncio.gather(self.voice_monitor, return_exceptions=True)
            self.voice_monitor = None
        try:
            await self.levels.close()
        finally:
            await music.close()
            for voice in list(self.voice_clients):
                await voice.disconnect(force=True)
            await super().close()

    async def on_voice_state_update(self, member, before, after):
        self.levels.refresh(member.guild)
        if self.user and member.id == self.user.id and after.channel is None:
            await music.stop_guild(member.guild.id)
        voice = member.guild.voice_client
        if voice is not None and voice.is_connected() and voice.channel is not None:
            self.idle_state(voice).check(asyncio.get_running_loop().time(), music.players.get(member.guild.id))


bot = Anthem()


async def connect_voice(interaction):
    member = interaction.user
    channel = member.voice.channel if member.voice else None
    if channel is None:
        await send_music_result(interaction, "Bạn hãy vào kênh thoại trước.")
        return None
    if not isinstance(channel, discord.VoiceChannel):
        await send_music_result(interaction, "Hãy dùng kênh thoại thông thường để thử bot.")
        return None
    voice = interaction.guild.voice_client
    if voice is not None:
        if voice.channel.id != channel.id:
            await send_music_result(interaction, "Bot đang ở kênh khác. Hãy vào cùng kênh với bot.")
            return None
    else:
        voice = await channel.connect(timeout=30, self_deaf=True)
    bot.idle_state(voice).notice_channel = interaction.channel
    return voice


music = Music(bot, connect_voice)
music.install()
bot.levels = ListeningLevels(bot, music)
bot.levels.install()
bot.playlists = Playlists(music)
bot.playlists.install()
install_help(bot.tree)


@bot.tree.command(name="join", description="Mời Capri Anthem vào kênh thoại của bạn")
@app_commands.guild_only()
async def join(interaction: discord.Interaction):
    await interaction.response.defer()
    async with bot.voice_lock:
        voice = await connect_voice(interaction)
        if voice:
            await interaction.followup.send(f"Đã vào {voice.channel.mention}.")


@bot.tree.command(name="leave", description="Dừng âm thanh và rời kênh thoại")
@app_commands.guild_only()
async def leave(interaction: discord.Interaction):
    await interaction.response.defer()
    async with bot.voice_lock:
        voice = interaction.guild.voice_client
        if voice is None:
            await interaction.followup.send("Bot hiện chưa ở trong kênh thoại.")
            return
        member = interaction.user
        if member.voice is None or member.voice.channel.id != voice.channel.id:
            await interaction.followup.send("Bạn hãy vào cùng kênh thoại với bot.", ephemeral=True)
            return
        await music.stop_guild(interaction.guild_id)
        await voice.disconnect(force=True)
        await interaction.followup.send("Đã rời kênh thoại.")


@bot.tree.error
async def command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", error)
    expired = isinstance(original, discord.NotFound) and original.code in {10015, 10062}
    if expired:
        logger.warning("Command %s interaction expired", interaction.command.name if interaction.command else "unknown")
        message = "Lượt gọi lệnh vừa hết hạn. Bạn hãy dùng lại lệnh một lần nhé."
    elif isinstance(original, MusicError):
        message = str(original)
    elif isinstance(original, TimeoutError):
        message = "Nguồn nhạc phản hồi quá lâu. Hãy thử lại."
    else:
        logger.error("Command %s failed", interaction.command.name if interaction.command else "unknown", exc_info=error)
        message = "Thao tác thất bại. Hãy kiểm tra quyền Kết Nối, Nói và nhật ký bot."
    try:
        if expired or (interaction.command and interaction.command.name == "play"):
            await send_music_result(interaction, message)
        elif interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        logger.warning("Could not deliver command error response")


async def main():
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("Hãy chạy anthem configure để nhập token.")
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(bot.close()))
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    log_directory = Path.home() / ".local/state/capri-anthem"
    log_directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), RotatingFileHandler(
            log_directory / "bot.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
        )],
    )
    try:
        asyncio.run(main())
    except FileNotFoundError:
        raise SystemExit("Hãy chạy anthem configure để nhập token.")
    except discord.LoginFailure:
        raise SystemExit("Token không hợp lệ. Chạy anthem configure để nhập lại.")
