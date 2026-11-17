import asyncio
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from levels import ListeningLevels, rank_values


class ListeningLevelsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.now = 0
        self.playing = True
        self.member = SimpleNamespace(id=7, bot=False, voice=SimpleNamespace(self_deaf=False, deaf=False))
        self.channel = SimpleNamespace(members=[self.member])
        self.voice = SimpleNamespace(channel=self.channel, is_connected=lambda: True,
                                     is_playing=lambda: self.playing)
        self.guild = SimpleNamespace(id=1, voice_client=self.voice, unavailable=False)
        self.bot = SimpleNamespace(guilds=[self.guild], is_ready=lambda: True)
        self.music = SimpleNamespace(players={1: SimpleNamespace(current=object())})
        self.levels = ListeningLevels(self.bot, self.music,
                                      path=Path(self.directory.name) / "levels.sqlite3", clock=lambda: self.now)
        self.levels.create_database()

    async def asyncTearDown(self):
        await self.levels.close()
        self.directory.cleanup()

    async def test_hack_rewards_current_audience_and_persists(self):
        second = SimpleNamespace(id=8, bot=False, voice=SimpleNamespace(self_deaf=False, deaf=False))
        self.channel.members.append(second)
        self.member.voice.self_deaf = True
        self.levels.refresh(self.guild)
        self.member.voice.self_deaf = False
        self.levels.refresh(self.guild)
        self.channel.members.append(SimpleNamespace(id=9, bot=False,
                                   voice=SimpleNamespace(self_deaf=False, deaf=False)))
        self.member.voice.self_deaf = True
        await self.levels.finish_hack(self.guild, completed=True)
        self.assertEqual(self.levels.read_rank(1, 7)[-1], 0)
        self.assertEqual(self.levels.read_rank(1, 8)[-1], 200)
        self.assertEqual(self.levels.read_rank(1, 9)[-1], 200)
        self.assertEqual(self.levels.read_rank(2, 8)[-1], 0)
        reopened = ListeningLevels(self.bot, self.music, path=self.levels.path)
        self.assertEqual(reopened.read_leaderboard(1)[0][-1], 200)
        self.assertEqual(rank_values(0, bonus=200)[0], 200)

    async def test_skipped_hack_no_reward(self):
        await self.levels.finish_hack(self.guild, completed=False)
        self.assertEqual(self.levels.read_rank(1, 7)[-1], 0)

    async def test_pause_resume_and_split_minutes(self):
        self.levels.refresh(self.guild)
        self.now = 30
        self.playing = False
        self.levels.refresh(self.guild)
        self.now = 90
        self.playing = True
        self.levels.refresh(self.guild)
        self.now = 120
        self.levels.refresh(self.guild)
        await self.levels.flush()
        milliseconds, _, _, _, _ = self.levels.read_rank(1, 7)
        self.assertEqual(milliseconds, 60000)
        self.assertEqual(rank_values(milliseconds), (10, 0, 25))

    async def test_deafened_members_and_bots_do_not_earn(self):
        self.channel.members.append(SimpleNamespace(id=9, bot=True, voice=self.member.voice))
        self.levels.refresh(self.guild)
        self.now = 12
        self.member.voice.self_deaf = True
        self.levels.refresh(self.guild)
        self.now = 72
        self.levels.refresh(self.guild)
        await self.levels.flush()
        self.assertEqual(self.levels.read_rank(1, 7)[0], 12000)
        self.assertEqual(self.levels.read_rank(1, 9)[0], 0)

    async def test_late_join_and_leave(self):
        self.levels.refresh(self.guild)
        self.now = 30
        self.channel.members.append(SimpleNamespace(id=8, bot=False, voice=self.member.voice))
        self.levels.refresh(self.guild)
        self.now = 60
        self.channel.members.remove(self.member)
        self.levels.refresh(self.guild)
        self.now = 90
        self.levels.refresh(self.guild)
        await self.levels.flush()
        self.assertEqual(self.levels.read_rank(1, 7)[0], 60000)
        self.assertEqual(self.levels.read_rank(1, 8)[0], 60000)

    async def test_test_tone_and_loading_do_not_earn(self):
        self.music.players[1].current = None
        self.levels.refresh(self.guild)
        self.now = 60
        self.music.players[1].current = object()
        self.playing = False
        self.levels.refresh(self.guild)
        self.now = 120
        self.levels.refresh(self.guild)
        await self.levels.flush()
        self.assertEqual(self.levels.read_rank(1, 7)[0], 0)

    async def test_disconnect_does_not_count_offline_time(self):
        self.levels.refresh(self.guild)
        self.now = 20
        self.levels.refresh_all(disconnected=True)
        self.now = 620
        self.levels.refresh_all()
        self.now = 660
        self.levels.refresh_all()
        await self.levels.flush()
        self.assertEqual(self.levels.read_rank(1, 7)[0], 60000)

    async def test_concurrent_flush_is_not_duplicated_and_survives_reopen(self):
        self.levels.pending[1, 7] = 60000
        await asyncio.gather(self.levels.flush(), self.levels.flush())
        reopened = ListeningLevels(self.bot, self.music, path=self.levels.path)
        reopened.create_database()
        self.assertEqual(reopened.read_rank(1, 7)[0], 60000)
        self.assertFalse(self.levels.pending)

    async def test_failed_save_retains_time_for_retry(self):
        self.levels.pending[1, 7] = 60000
        with patch.object(self.levels, "write_batch", side_effect=sqlite3.OperationalError("locked")):
            with self.assertRaises(sqlite3.OperationalError):
                await self.levels.flush()
        self.assertEqual(self.levels.pending[1, 7], 60000)
        await self.levels.flush()
        self.assertEqual(self.levels.read_rank(1, 7)[0], 60000)

    async def test_server_scoping_and_leaderboard_order(self):
        self.levels.pending.update({(1, 7): 60000, (1, 8): 120000, (2, 7): 900000})
        await self.levels.flush()
        self.assertEqual(self.levels.read_leaderboard(1), [(8, 120000, 0, 0, 0), (7, 60000, 0, 0, 0)])
        self.assertEqual(self.levels.read_rank(1, 7)[1], 2)
        self.assertEqual(self.levels.read_rank(2, 7)[0], 900000)

    async def test_saved_orders_count_in_both_rankings_without_changing_listening_time(self):
        self.levels.write_batch({(1, 7): 594000, (1, 8): 600000})
        self.levels.increment_orders(1, 7, 3)
        self.levels.increment_orders(1, 9, 104)
        self.levels.increment_orders(2, 7, 200)
        reopened = ListeningLevels(self.bot, self.music, path=self.levels.path)
        reopened.create_database()
        self.assertEqual(reopened.read_rank(1, 7), (594000, 2, 3, 0, 0))
        self.assertEqual(reopened.read_rank(1, 9), (0, 1, 104, 0, 0))
        self.assertEqual(reopened.read_rank(1, 10), (0, None, 0, 0, 0))
        self.assertEqual(reopened.read_leaderboard(1), [(9, 0, 104, 0, 0), (7, 594000, 3, 0, 0), (8, 600000, 0, 0, 0)])
        self.assertEqual(rank_values(594000, 3), (105, 3, 130))
        self.assertEqual(rank_values(0, 104), (208, 5, 225))

    async def test_completion_requires_requester_to_remain_eligible(self):
        self.levels.begin_completion(self.guild, 7)
        self.playing = False
        self.levels.refresh(self.guild)
        self.assertEqual(self.levels.end_completion(self.guild, completed=True), 7)
        self.assertIsNone(self.levels.end_completion(self.guild, completed=True))

        self.levels.begin_completion(self.guild, 7)
        self.member.voice.self_deaf = True
        self.levels.refresh(self.guild)
        self.member.voice.self_deaf = False
        self.assertIsNone(self.levels.end_completion(self.guild, completed=True))

        self.levels.begin_completion(self.guild, 7)
        self.assertIsNone(self.levels.end_completion(self.guild))
        self.assertIsNone(self.levels.end_completion(self.guild, completed=True))

    async def test_completion_bonus_changes_total_xp_and_ranking(self):
        self.levels.write_batch({(1, 7): 60000, (1, 8): 90000})
        await self.levels.record_order(1, 7)
        self.assertEqual(rank_values(60000, 1), (12, 0, 25))
        await self.levels.record_completion(1, 7)
        self.assertEqual(self.levels.read_rank(1, 7), (60000, 1, 1, 1, 0))
        self.assertEqual(self.levels.read_leaderboard(1)[0], (7, 60000, 1, 1, 0))
        self.assertEqual(rank_values(60000, 1, 1), (17, 0, 25))

    async def test_clean_shutdown_saves_partial_minute(self):
        await self.levels.start()
        self.levels.refresh(self.guild)
        self.now = 24
        await self.levels.close()
        self.assertEqual(self.levels.read_rank(1, 7)[0], 24000)

    async def test_level_thresholds(self):
        for level, threshold, next_threshold in (
            (1, 25, 55), (2, 55, 90), (10, 475, 550), (50, 7375, 7650),
            (100, 27250, 27775), (101, 27775, 28305),
        ):
            with self.subTest(level=level):
                self.assertEqual(rank_values(threshold * 6000), (threshold, level, next_threshold))
                self.assertEqual(rank_values(threshold * 6000 - 1), (threshold - 1, level - 1, threshold))


if __name__ == "__main__":
    unittest.main()
