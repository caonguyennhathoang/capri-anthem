import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from music import Music, MusicError, PlaybackControls, Player, Track


class FakeVoice:
    def __init__(self):
        self.channel = SimpleNamespace(id=10)
        self.playing = True
        self.paused = False

    def is_connected(self):
        return True

    def is_playing(self):
        return self.playing and not self.paused

    def is_paused(self):
        return self.paused

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.playing = False
        self.paused = False


class PlaybackControlsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.voice = FakeVoice()
        self.guild = SimpleNamespace(id=1, voice_client=self.voice, me=object())
        self.channel = SimpleNamespace(send=AsyncMock(), permissions_for=Mock(return_value=SimpleNamespace(embed_links=True)))
        self.music = Music(SimpleNamespace(voice_lock=asyncio.Lock()), AsyncMock())
        self.player = Player(self.guild, self.channel, self.music)
        self.track = Track("Example", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", 180)
        self.player.current = self.track
        self.music.players[1] = self.player
        self.panel = PlaybackControls(self.music, self.player, self.track)
        self.panel.message = SimpleNamespace(edit=AsyncMock())
        self.player.panel = self.panel

    async def asyncTearDown(self):
        await self.music.close()
        self.panel.stop()

    def interaction(self, channel_id=10):
        return SimpleNamespace(
            guild_id=1, guild=self.guild, channel=self.channel,
            user=SimpleNamespace(id=7, voice=SimpleNamespace(channel=SimpleNamespace(id=channel_id))),
            response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: True),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    async def test_toggle_changes_voice_and_label(self):
        await self.panel.toggle.callback(self.interaction())
        self.assertTrue(self.voice.paused)
        self.assertEqual(self.panel.toggle.label, "Tiếp tục")
        await self.panel.toggle.callback(self.interaction())
        self.assertFalse(self.voice.paused)
        self.assertEqual(self.panel.toggle.label, "Tạm dừng")

    async def test_slash_commands_update_same_panel(self):
        await self.music.perform(self.interaction(), "pause")
        self.assertEqual(self.panel.toggle.label, "Tiếp tục")
        await self.music.perform(self.interaction(), "resume")
        self.assertEqual(self.panel.toggle.label, "Tạm dừng")

    async def test_progress_freezes_on_pause_and_resumes(self):
        self.panel.running_since -= 65
        await self.panel.toggle.callback(self.interaction())
        self.assertIn("01:05", self.panel.content())
        self.assertIn("03:00", self.panel.content())
        self.assertIsNone(self.panel.running_since)
        await self.panel.toggle.callback(self.interaction())
        self.panel.running_since -= 3
        self.assertIn("01:08", self.panel.content())
        await self.panel.retire()
        self.assertIn("Đã kết thúc", self.panel.content())
        self.assertIsNone(self.panel.running_since)

    async def test_paused_panel_updates_next_track_without_advancing_progress(self):
        self.panel.running_since -= 65
        await self.panel.toggle.callback(self.interaction())
        self.panel.message.edit.reset_mock()
        await self.panel.refresh()
        self.panel.message.edit.assert_not_awaited()
        self.player.pending.append(Track("Next", self.track.url, 90))
        await self.panel.refresh()
        embed = self.panel.message.edit.call_args.kwargs["embed"]
        self.assertEqual(embed.fields[0].name, "Tiếp theo")
        self.assertEqual(embed.fields[0].value, "Next")
        self.assertIn("01:05", embed.description)

    async def test_queued_track_records_requester_and_hack_panel_credits_capri(self):
        self.music.connect_voice.return_value = self.voice
        with patch.object(self.player, "add") as add:
            await self.music.enqueue_tracks(self.interaction(), [self.track])
        queued = add.call_args.args[0]
        self.assertIsNone(self.track.requester_id)
        self.panel.track = queued
        self.assertIn("<@7>", self.panel.display()["embed"].description)
        queued.surprise = True
        self.assertIn("Capri đã chiếm sóng", self.panel.display()["embed"].description)
        self.assertNotIn("<@7>", self.panel.display()["embed"].description)

    async def test_other_voice_channel_is_rejected(self):
        with self.assertRaises(MusicError):
            await self.panel.toggle.callback(self.interaction(channel_id=20))
        self.assertFalse(self.voice.paused)

    async def test_old_panel_cannot_control_next_track(self):
        self.player.current = Track("Next", self.track.url, 90)
        with self.assertRaises(MusicError):
            await self.panel.skip.callback(self.interaction())
        self.assertFalse(self.player.skip_requested.is_set())

    async def test_queue_button_replies_privately(self):
        self.player.pending.append(Track("Next", self.track.url, 90))
        interaction = self.interaction()
        await self.panel.queue.callback(interaction)
        args, kwargs = interaction.followup.send.call_args
        self.assertIn("Example", args[0])
        self.assertIn("Next", args[0])
        self.assertTrue(kwargs["ephemeral"])

    async def test_skip_disables_old_buttons(self):
        await self.panel.repeat.callback(self.interaction())
        self.assertEqual(self.panel.repeat.label, "Tắt lặp")
        await self.panel.skip.callback(self.interaction())
        self.assertTrue(self.player.skip_requested.is_set())
        self.assertTrue(all(item.disabled for item in self.panel.children))
        with self.assertRaises(MusicError):
            await self.panel.skip.callback(self.interaction())

    async def test_stop_clears_queue_and_retires_panel(self):
        self.player.pending.append(self.track)
        await self.panel.stop_playback.callback(self.interaction())
        self.assertFalse(self.player.pending)
        self.assertNotIn(1, self.music.players)
        self.assertFalse(self.voice.playing)
        self.assertTrue(all(item.disabled for item in self.panel.children))

    async def test_playback_creates_and_retires_buttons(self):
        source = Mock()
        message = SimpleNamespace(edit=AsyncMock())
        self.channel.send.return_value = message
        self.voice.play = lambda audio, after: asyncio.get_running_loop().call_soon(after, None)
        with patch("music.discord.FFmpegPCMAudio", return_value=source), \
                patch("music.discord.PCMVolumeTransformer", side_effect=lambda audio, volume: audio):
            await self.player.play_file(self.track, "test.webm")
        panel = self.channel.send.call_args.kwargs["view"]
        embed = self.channel.send.call_args.kwargs["embed"]
        self.assertEqual(embed.title, self.track.title)
        self.assertTrue(embed.thumbnail.url.endswith("/dQw4w9WgXcQ/mqdefault.jpg"))
        self.assertEqual(len(panel.children), 6)
        self.assertTrue(all(item.disabled for item in panel.children))
        self.assertTrue(panel.is_finished())
        self.assertIsNone(self.player.panel)
        source.cleanup.assert_called_once()

    async def test_repeat_reuses_file_and_panel_then_finishes_when_disabled(self):
        self.track.requester_id = 7
        levels = Mock(record_completion=AsyncMock())
        levels.end_completion.side_effect = lambda guild, completed=False: 7 if completed else None
        self.music.bot.levels = levels
        message = SimpleNamespace(edit=AsyncMock())
        self.channel.send.return_value = message
        callbacks = asyncio.Queue()
        self.voice.play = lambda audio, after: callbacks.put_nowait(after)
        with patch("music.discord.FFmpegPCMAudio", side_effect=lambda *args, **kwargs: Mock()) as audio, \
                patch("music.discord.PCMVolumeTransformer", side_effect=lambda source, volume: source):
            playback = asyncio.create_task(self.player.play_file(self.track, "test.webm"))
            try:
                finish = await asyncio.wait_for(callbacks.get(), timeout=1)
                panel = self.player.panel
                await panel.repeat.callback(self.interaction())
                self.assertEqual(panel.repeat.label, "Tắt lặp")
                self.assertEqual(panel.display()["embed"].fields[0].name, "Lặp bài")
                finish(None)
                finish = await asyncio.wait_for(callbacks.get(), timeout=1)
                self.assertIs(self.player.panel, panel)
                self.assertIn("00:00", panel.progress())
                await panel.repeat.callback(self.interaction())
                self.assertEqual(panel.repeat.label, "Lặp bài")
                finish(None)
                await asyncio.wait_for(playback, timeout=1)
            finally:
                playback.cancel()
                await asyncio.gather(playback, return_exceptions=True)
        self.channel.send.assert_awaited_once()
        levels.begin_completion.assert_called_once_with(self.guild, 7)
        levels.record_completion.assert_awaited_once_with(self.guild.id, 7)
        self.assertEqual([call.args[0] for call in audio.call_args_list], ["test.webm", "test.webm"])

    async def test_panel_falls_back_to_text_without_embed_permission(self):
        self.channel.permissions_for.return_value.embed_links = False
        self.voice.play = lambda audio, after: asyncio.get_running_loop().call_soon(after, None)
        with patch("music.discord.FFmpegPCMAudio"), patch("music.discord.PCMVolumeTransformer"):
            await self.player.play_file(self.track, "test.webm")
        args, kwargs = self.channel.send.call_args
        self.assertIn("Đang phát", args[0])
        self.assertIsNone(kwargs["embed"])
        self.assertIsInstance(kwargs["view"], PlaybackControls)

    async def test_ten_random_tracks_then_manual_order_still_counts(self):
        levels = SimpleNamespace(record_order=AsyncMock(), refresh=Mock())
        self.music.bot.levels = levels
        self.music.connect_voice.return_value = self.voice
        self.player.add = Mock(side_effect=self.player.pending.append)
        tracks = [Track(f"Random {i}", self.track.url, 60, earns_order_xp=False)
                  for i in range(10)]
        self.assertEqual(await self.music.enqueue_tracks(self.interaction(), tracks), 10)
        levels.record_order.assert_not_awaited()
        await self.music.enqueue(self.interaction(), self.track)
        levels.record_order.assert_awaited_once_with(1, 7, 1)
        self.assertFalse(self.player.pending[0].earns_order_xp)
        self.assertTrue(self.player.pending[-1].earns_order_xp)

    async def test_random_playback_has_no_completion_bonus_then_manual_does(self):
        levels = SimpleNamespace(refresh=Mock(), begin_completion=Mock(),
                                 end_completion=Mock(return_value=7), record_completion=AsyncMock())
        self.music.bot.levels = levels
        self.voice.play = lambda audio, after: asyncio.get_running_loop().call_soon(after, None)
        from dataclasses import replace
        with patch("music.discord.FFmpegPCMAudio"), patch("music.discord.PCMVolumeTransformer"):
            await self.player.play_file(replace(self.track, requester_id=7, earns_order_xp=False), "test.webm")
            levels.begin_completion.assert_not_called()
            levels.record_completion.assert_not_awaited()
            await self.player.play_file(replace(self.track, requester_id=7), "test.webm")
        levels.begin_completion.assert_called_once_with(self.guild, 7)
        levels.record_completion.assert_awaited_once_with(1, 7)

    async def test_hack_reward_only_first_natural_playback(self):
        levels = SimpleNamespace(refresh=Mock(), finish_hack=AsyncMock(),
                                 begin_completion=Mock(), record_completion=AsyncMock())
        self.music.bot.levels = levels
        self.track.surprise = True
        self.voice.play = lambda audio, after: asyncio.get_running_loop().call_soon(after, None)
        with patch("music.discord.FFmpegPCMAudio"), patch("music.discord.PCMVolumeTransformer"):
            await self.player.play_file(self.track, "test.webm")
        levels.finish_hack.assert_awaited_once_with(self.guild, completed=True)
        levels.record_completion.assert_not_awaited()

    async def test_skipped_hack_does_not_award(self):
        levels = SimpleNamespace(refresh=Mock(), finish_hack=AsyncMock())
        self.music.bot.levels = levels
        self.track.surprise = True
        def play(audio, after):
            self.player.skip_requested.set()
            asyncio.get_running_loop().call_soon(after, None)
        self.voice.play = play
        with patch("music.discord.FFmpegPCMAudio"), patch("music.discord.PCMVolumeTransformer"):
            await self.player.play_file(self.track, "test.webm")
        levels.finish_hack.assert_awaited_once_with(self.guild, completed=False)

    async def test_hack_respects_cooldown_and_probability(self):
        self.player.hack_channel = Mock(return_value=object())
        self.player.next_hack_at = asyncio.get_running_loop().time() + 900
        with patch("music.random.random", return_value=0) as draw:
            self.assertFalse(await self.player.maybe_hack())
            draw.assert_not_called()
        self.player.next_hack_at = 0
        with patch("music.random.random", return_value=.30), patch("music.extract", AsyncMock()) as search:
            self.assertFalse(await self.player.maybe_hack())
            search.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
