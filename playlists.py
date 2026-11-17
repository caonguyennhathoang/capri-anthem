"""Private and public playlists stored as YouTube references."""

import asyncio
from contextlib import closing
from pathlib import Path
from random import shuffle
from secrets import randbits
import sqlite3

import discord
from discord import app_commands

from music import MusicError, Track, extract, youtube_query


PAGE_SIZE = 10


def page_bounds(page, total):
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), pages)
    return page, pages, (page - 1) * PAGE_SIZE


class MoveTrack(discord.ui.Modal, title="Đổi vị trí bài nhạc"):
    position = discord.ui.TextInput(label="Vị trí mới trong cả playlist", max_length=10)

    def __init__(self, view):
        super().__init__(timeout=180)
        self.playlist_view = view

    async def on_submit(self, interaction):
        try:
            position = int(str(self.position))
        except ValueError:
            await interaction.response.send_message("Nhập vị trí bằng số nguyên.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.playlist_view.update_track(interaction, position)


class AddPlaylistTrack(discord.ui.Modal, title="Thêm bài hát"):
    link = discord.ui.TextInput(label="Link một video YouTube", max_length=200)

    def __init__(self, view):
        super().__init__(timeout=180)
        self.view = view

    async def on_submit(self, interaction):
        await interaction.response.defer()
        playlists = self.view.playlists
        try:
            target = youtube_query(str(self.link))
            if target.startswith("ytsearch"):
                raise MusicError("Hãy dán link một video YouTube.")
            async with playlists.music.search_slots:
                info = await extract(target, search=True)
            track = Track.from_info(info)
            added = await asyncio.to_thread(playlists.save_to_id, interaction.user.id,
                                            self.view.playlist_id, track)
        except MusicError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except (TimeoutError, OSError, ValueError, TypeError):
            await interaction.followup.send("Chưa đọc được video. Hãy kiểm tra link và thử lại.", ephemeral=True)
            return
        if not added:
            await interaction.followup.send("Bài này đã có trong playlist.", ephemeral=True)
            return
        await self.view.redraw(interaction, self.view.page, self.view.playlist_id,
                               notice="Đã thêm bài vào cuối playlist.")


class PlaylistInfo(discord.ui.View):
    def __init__(self, playlists, viewer_id, playlist_id, page, pages, options, selected_id,
                 *, can_edit=False):
        super().__init__(timeout=600)
        self.playlists = playlists
        self.viewer_id = viewer_id
        self.playlist_id = playlist_id
        self.page = page
        self.selected_id = selected_id
        self.previous.disabled = page == 1
        self.next_page.disabled = page == pages
        if not can_edit:
            self.remove_item(self.add_track)
        if playlist_id is None or not options:
            self.remove_item(self.remove_track)
            self.remove_item(self.move_track)
        else:
            self.remove_track.disabled = self.move_track.disabled = selected_id is None
        if options:
            menu = discord.ui.Select(
                placeholder="Mở playlist" if playlist_id is None else "Chọn bài để chỉnh sửa",
                options=options, row=0,
            )

            async def select(interaction):
                selected = int(menu.values[0])
                if self.playlist_id is None:
                    await self.refresh(interaction, 1, selected)
                else:
                    await self.refresh(interaction, self.page, self.playlist_id, selected)

            menu.callback = select
            self.add_item(menu)
        if playlist_id is None:
            self.remove_item(self.back)

    async def interaction_check(self, interaction):
        if interaction.user.id == self.viewer_id:
            return True
        await interaction.response.send_message("Hãy mở /playlist info của bạn.", ephemeral=True)
        return False

    async def redraw(self, interaction, page, playlist_id, selected_id=None, notice=None):
        embed, view = await self.playlists.info(
            self.viewer_id, playlist_id, page, selected_id
        )
        await interaction.edit_original_response(
            content=notice, embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none()
        )
        self.stop()

    async def refresh(self, interaction, page, playlist_id, selected_id=None):
        await interaction.response.defer()
        try:
            await self.redraw(interaction, page, playlist_id, selected_id)
        except MusicError as error:
            await interaction.edit_original_response(content=str(error), embed=None, view=None)
            self.stop()

    async def update_track(self, interaction, position=None):
        try:
            await asyncio.to_thread(
                self.playlists.edit_track, interaction.user.id, self.playlist_id,
                self.selected_id, position
            )
        except MusicError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        page = self.page if position is None else (position - 1) // PAGE_SIZE + 1
        notice = "Đã xóa bài." if position is None else f"Đã chuyển bài đến vị trí {position}."
        try:
            await self.redraw(interaction, page, playlist_id=self.playlist_id, notice=notice)
        except MusicError as error:
            await interaction.edit_original_response(content=str(error), embed=None, view=None)
            self.stop()

    @discord.ui.button(label="Trang trước", row=1)
    async def previous(self, interaction, button):
        await self.refresh(interaction, self.page - 1, self.playlist_id)

    @discord.ui.button(label="Trang sau", row=1)
    async def next_page(self, interaction, button):
        await self.refresh(interaction, self.page + 1, self.playlist_id)

    @discord.ui.button(label="Playlist của tôi", row=1)
    async def back(self, interaction, button):
        await self.refresh(interaction, 1, None)

    @discord.ui.button(label="Đổi vị trí", style=discord.ButtonStyle.primary, row=2)
    async def move_track(self, interaction, button):
        await interaction.response.send_modal(MoveTrack(self))

    @discord.ui.button(label="Thêm bài hát", emoji="➕", style=discord.ButtonStyle.primary, row=2)
    async def add_track(self, interaction, button):
        await interaction.response.send_modal(AddPlaylistTrack(self))

    @discord.ui.button(label="Xóa bài", style=discord.ButtonStyle.danger, row=2)
    async def remove_track(self, interaction, button):
        await interaction.response.defer()
        await self.update_track(interaction)


class SaveTrack(discord.ui.Modal, title="Lưu vào playlist"):
    playlist_name = discord.ui.TextInput(label="Tên playlist", max_length=60)

    def __init__(self, playlists, track):
        super().__init__(timeout=180)
        self.playlists = playlists
        self.track = track

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            saved = await asyncio.to_thread(
                self.playlists.save, interaction.user.id, str(self.playlist_name), self.track
            )
        except MusicError as error:
            message = str(error)
        else:
            message = "Đã lưu bài vào playlist." if saved else "Bài này đã có trong playlist."
        await interaction.followup.send(message, ephemeral=True)


class Playlists:
    def __init__(self, music, path=None):
        self.music = music
        self.path = Path(path) if path else Path.home() / ".local/state/capri-anthem/playlists.sqlite3"

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY,
                    owner_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    is_public INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (owner_id, name_key)
                );
                CREATE TABLE IF NOT EXISTS playlist_tracks (
                    id INTEGER PRIMARY KEY,
                    playlist_id INTEGER NOT NULL REFERENCES playlists(id),
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    duration INTEGER NOT NULL,
                    artist TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    UNIQUE (playlist_id, url)
                );
            """)
            db.execute("BEGIN IMMEDIATE")
            if "is_public" not in {row[1] for row in db.execute("PRAGMA table_info(playlists)")}:
                db.execute("ALTER TABLE playlists ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0")
            if "position" not in {row[1] for row in db.execute("PRAGMA table_info(playlist_tracks)")}:
                db.execute("ALTER TABLE playlist_tracks ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
                db.execute("UPDATE playlist_tracks SET position = id")
            db.execute("""
                CREATE INDEX IF NOT EXISTS playlist_tracks_order
                ON playlist_tracks (playlist_id, position, id)
            """)

    def save_modal(self, track):
        return SaveTrack(self, track)

    @staticmethod
    def normalize(name):
        name = " ".join(name.split())
        if not 1 <= len(name) <= 60:
            raise MusicError("Tên playlist cần có từ 1 đến 60 ký tự.")
        return name

    def create(self, owner_id, name, is_public=False):
        name = self.normalize(name)
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute("""
                INSERT INTO playlists (id, owner_id, name, name_key, is_public) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (owner_id, name_key) DO NOTHING
            """, (randbits(52) + 1, owner_id, name, name.casefold(), is_public))
            return cursor.rowcount == 1

    def lookup(self, db, owner_id, name):
        row = db.execute("SELECT id FROM playlists WHERE owner_id = ? AND name_key = ?",
                         (owner_id, self.normalize(name).casefold())).fetchone()
        if row is None:
            raise MusicError("Bạn chưa có playlist tên này. Dùng /playlist create để tạo.")
        return row[0]

    def save(self, owner_id, name, track):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            playlist_id = self.lookup(db, owner_id, name)
            return self.insert_track(db, playlist_id, track)

    def save_to_id(self, owner_id, playlist_id, track):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM playlists WHERE id = ? AND owner_id = ?",
                              (playlist_id, owner_id)).fetchone():
                raise MusicError("Playlist này đã bị xóa hoặc không thuộc về bạn.")
            return self.insert_track(db, playlist_id, track)

    @staticmethod
    def insert_track(db, playlist_id, track):
        cursor = db.execute("""
                INSERT INTO playlist_tracks (id, playlist_id, title, url, duration, artist, position)
                VALUES (?, ?, ?, ?, ?, ?, (
                    SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_tracks WHERE playlist_id = ?
                )) ON CONFLICT (playlist_id, url) DO NOTHING
            """, (randbits(52) + 1, playlist_id, track.title, track.url, track.duration, track.artist,
                  playlist_id))
        return cursor.rowcount == 1

    def delete(self, owner_id, name):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            playlist_id = self.lookup(db, owner_id, name)
            db.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
            db.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))

    def set_visibility(self, owner_id, name, is_public):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            playlist_id = self.lookup(db, owner_id, name)
            db.execute("UPDATE playlists SET is_public = ? WHERE id = ?", (is_public, playlist_id))
            return playlist_id

    def public_names(self, page):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("""
                SELECT p.name, COUNT(t.id), p.id, p.owner_id FROM playlists p
                LEFT JOIN playlist_tracks t ON t.playlist_id = p.id
                WHERE p.is_public = 1 GROUP BY p.id ORDER BY p.name_key, p.id
                LIMIT 11 OFFSET ?
            """, ((page - 1) * 10,)).fetchall()

    def resolve(self, db, viewer_id, name, public_id):
        if name is not None and public_id is None:
            return self.lookup(db, viewer_id, name)
        if name is None and public_id is not None:
            row = db.execute("SELECT id FROM playlists WHERE id = ? AND is_public = 1",
                             (public_id,)).fetchone()
            if row is not None:
                return row[0]
            raise MusicError("Không tìm thấy playlist công khai theo mã này.")
        raise MusicError("Nhập tên playlist của bạn hoặc mã playlist công khai.")

    def edit_track(self, owner_id, playlist_id, track_id, position=None):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            owner = db.execute("SELECT owner_id FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
            if owner != (owner_id,):
                raise MusicError("Chỉ chủ playlist mới có thể chỉnh sửa.")
            if position is None:
                removed = db.execute("DELETE FROM playlist_tracks WHERE playlist_id = ? AND id = ?",
                                     (playlist_id, track_id))
                if not removed.rowcount:
                    raise MusicError("Bài này đã bị xóa. Mở lại /playlist info để cập nhật.")
                return
            ids = [row[0] for row in db.execute("""
                SELECT id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position, id
            """, (playlist_id,))]
            if track_id not in ids:
                raise MusicError("Bài này đã bị xóa. Mở lại /playlist info để cập nhật.")
            if not 1 <= position <= len(ids):
                raise MusicError(f"Vị trí phải từ 1 đến {len(ids)}.")
            old_position = ids.index(track_id)
            ids.pop(old_position)
            ids.insert(position - 1, track_id)
            db.executemany("UPDATE playlist_tracks SET position = ? WHERE id = ?",
                           enumerate(ids, 1))

    def tracks(self, owner_id, name=None, public_id=None):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("BEGIN")
            playlist_id = self.resolve(db, owner_id, name, public_id)
            return [Track(*row) for row in db.execute("""
                SELECT title, url, duration, artist FROM playlist_tracks
                WHERE playlist_id = ? ORDER BY position, id
            """, (playlist_id,))]

    def info_page(self, viewer_id, playlist_id, page, name, public_id):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("BEGIN")
            if name is not None or public_id is not None:
                playlist_id = self.resolve(db, viewer_id, name, public_id)
            if playlist_id is None:
                total = db.execute("SELECT COUNT(*) FROM playlists WHERE owner_id = ?",
                                   (viewer_id,)).fetchone()[0]
                page, pages, offset = page_bounds(page, total)
                rows = db.execute("""
                    SELECT p.id, p.name, p.is_public, COUNT(t.id)
                    FROM playlists p LEFT JOIN playlist_tracks t ON t.playlist_id = p.id
                    WHERE p.owner_id = ? GROUP BY p.id ORDER BY p.name_key
                    LIMIT ? OFFSET ?
                """, (viewer_id, PAGE_SIZE, offset)).fetchall()
                return None, None, rows, total, page, pages, offset

            details = db.execute("""
                SELECT name, owner_id, is_public FROM playlists
                WHERE id = ? AND (owner_id = ? OR is_public = 1)
            """, (playlist_id, viewer_id)).fetchone()
            if details is None:
                raise MusicError("Playlist đã bị xóa hoặc đã chuyển sang riêng tư.")
            total = db.execute("SELECT COUNT(*) FROM playlist_tracks WHERE playlist_id = ?",
                               (playlist_id,)).fetchone()[0]
            page, pages, offset = page_bounds(page, total)
            rows = db.execute("""
                SELECT id, title, url, duration, artist FROM playlist_tracks
                WHERE playlist_id = ? ORDER BY position, id LIMIT ? OFFSET ?
            """, (playlist_id, PAGE_SIZE, offset)).fetchall()
            return playlist_id, details, rows, total, page, pages, offset

    async def info(self, viewer_id, playlist_id=None, page=1, selected_id=None,
                   *, name=None, public_id=None):
        playlist_id, details, rows, total, page, pages, offset = await asyncio.to_thread(
            self.info_page, viewer_id, playlist_id, page, name, public_id
        )
        options = []
        lines = []
        if details is None:
            embed = discord.Embed(title="Playlist của bạn", color=0xFF2467)
            for item_id, title, is_public, count in rows:
                status = f"Công khai · Mã `{item_id}`" if is_public else "Riêng tư"
                lines.append(f"**{discord.utils.escape_markdown(title)}** · {count} bài · {status}")
                options.append(discord.SelectOption(label=title, value=str(item_id)))
            embed.description = "\n".join(lines) or "Dùng `/playlist create` để tạo playlist."
            embed.set_footer(text=f"Trang {page}/{pages} · {total} playlist")
        else:
            title, owner_id, is_public = details
            embed = discord.Embed(title=discord.utils.escape_markdown(title), color=0xFF2467)
            status = f"Công khai · Mã `{playlist_id}`" if is_public else "Riêng tư"
            embed.description = f"{status} · Chủ playlist <@{owner_id}>"
            for index, (track_id, *data) in enumerate(rows, offset + 1):
                label = Track(*data).label
                text = discord.utils.escape_markdown(label[:105])
                lines.append(f"**{index}.** " + (f"**{text}** ← Đã chọn" if track_id == selected_id else text))
                if viewer_id == owner_id:
                    options.append(discord.SelectOption(label=f"{index}. {label}"[:100], value=str(track_id),
                                                        default=track_id == selected_id))
            # Split the track list across fields within Discord's per-field limit.
            for start in range(0, len(lines), 4):
                embed.add_field(name="Danh sách bài" if start == 0 else "\u200b",
                                value="\n".join(lines[start:start + 4]), inline=False)
            if not lines:
                embed.add_field(name="Danh sách bài", value="Playlist chưa có bài.", inline=False)
            embed.set_footer(text=f"Trang {page}/{pages} · {total} bài")
        if not any(option.default for option in options):
            selected_id = None
        view = PlaylistInfo(self, viewer_id, playlist_id, page, pages, options, selected_id,
                            can_edit=details is not None and viewer_id == details[1])
        return embed, view

    def install(self):
        group = app_commands.Group(name="playlist", description="Playlist nhạc riêng tư và công khai",
                                   guild_only=True)

        visibility_choices = [
            app_commands.Choice(name="Riêng tư", value="private"),
            app_commands.Choice(name="Công khai", value="public"),
        ]

        @group.command(name="create", description="Tạo playlist, mặc định là riêng tư")
        @app_commands.choices(visibility=visibility_choices)
        async def create(interaction: discord.Interaction, name: str, visibility: str = "private"):
            await interaction.response.defer(ephemeral=True)
            created = await asyncio.to_thread(self.create, interaction.user.id, name, visibility == "public")
            message = "Đã tạo playlist. Bấm Lưu vào playlist dưới bài đang phát để thêm bài." if created else "Bạn đã có playlist tên này."
            await interaction.followup.send(message, ephemeral=True)

        @group.command(name="visibility", description="Đổi playlist của bạn sang riêng tư hoặc công khai")
        @app_commands.choices(visibility=visibility_choices)
        async def visibility(interaction: discord.Interaction, name: str, visibility: str):
            await interaction.response.defer(ephemeral=True)
            is_public = visibility == "public"
            playlist_id = await asyncio.to_thread(self.set_visibility, interaction.user.id, name, is_public)
            message = (f"Playlist đã công khai. Mọi người có thể dùng `/playlist play public public_id:{playlist_id}`."
                       if is_public else "Playlist đã chuyển sang riêng tư.")
            await interaction.followup.send(message, ephemeral=True)

        @group.command(name="public", description="Tìm playlist công khai và mã để phát")
        async def public(interaction: discord.Interaction, page: app_commands.Range[int, 1, 1_000_000] = 1):
            await interaction.response.defer(ephemeral=True)
            rows = await asyncio.to_thread(self.public_names, page)
            lines = [f"**{discord.utils.escape_markdown(title)}** · <@{owner_id}> · {count} bài · Mã `{playlist_id}`"
                     for title, count, playlist_id, owner_id in rows[:10]]
            if len(rows) > 10:
                lines.append(f"Dùng `/playlist public page:{page + 1}` để xem tiếp.")
            await interaction.followup.send("\n".join(lines) or "Trang này chưa có playlist công khai.",
                                            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

        @group.command(name="info", description="Xem playlist, lật trang và chỉnh danh sách bài của bạn")
        async def info(interaction: discord.Interaction, name: str | None = None,
                       public_id: app_commands.Range[int, 1] | None = None):
            await interaction.response.defer(ephemeral=True)
            embed, view = await self.info(interaction.user.id, name=name, public_id=public_id)
            await interaction.edit_original_response(embed=embed, view=view,
                                                     allowed_mentions=discord.AllowedMentions.none())

        @group.command(name="delete", description="Xóa playlist cá nhân và danh sách bài đã lưu trong đó")
        async def delete(interaction: discord.Interaction, name: str):
            await interaction.response.defer(ephemeral=True)
            await asyncio.to_thread(self.delete, interaction.user.id, name)
            await interaction.followup.send("Đã xóa playlist của bạn.", ephemeral=True)

        play_group = app_commands.Group(
            name="play", description="Phát playlist cá nhân hoặc công khai", parent=group
        )
        order_choices = [
            app_commands.Choice(name="Theo thứ tự", value="ordered"),
            app_commands.Choice(name="Xáo trộn", value="shuffle"),
        ]

        async def enqueue_playlist(interaction, order, *, name=None, public_id=None):
            await interaction.response.defer(ephemeral=True)
            tracks = await asyncio.to_thread(self.tracks, interaction.user.id, name, public_id)
            if not tracks:
                raise MusicError("Playlist này chưa có bài.")
            if order == "shuffle":
                shuffle(tracks)
            async with self.music.bot.voice_lock:
                count = await self.music.enqueue_tracks(interaction, tracks)
            mode = "xáo trộn" if order == "shuffle" else "theo thứ tự đã lưu"
            message = f"Đã thêm {count} bài từ playlist, phát {mode}."
            if count < len(tracks):
                message += f" Hàng đợi đã đầy, còn {len(tracks) - count} bài trong playlist."
            await interaction.followup.send(message, ephemeral=True)

        @play_group.command(name="name", description="Phát playlist của bạn theo tên")
        @app_commands.describe(name="Tên playlist của bạn", order="Thứ tự phát trong lượt này")
        @app_commands.choices(order=order_choices)
        async def play_name(interaction: discord.Interaction, name: str, order: str = "ordered"):
            await enqueue_playlist(interaction, order, name=name)

        @play_group.command(name="public", description="Phát playlist công khai theo ID")
        @app_commands.describe(public_id="ID playlist công khai", order="Thứ tự phát trong lượt này")
        @app_commands.choices(order=order_choices)
        async def play_public(interaction: discord.Interaction, public_id: app_commands.Range[int, 1],
                              order: str = "ordered"):
            await enqueue_playlist(interaction, order, public_id=public_id)

        self.music.bot.tree.add_command(group)
