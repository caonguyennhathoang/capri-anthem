import asyncio
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

    async def setup_hook(self):
        await asyncio.to_thread(self.playlists.initialize)
        await self.levels.start()

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
        return voice
    return await channel.connect(timeout=30, self_deaf=True)


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
