import asyncio
from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord
import bot
from music import SearchResults, Track, acknowledge_play, send_music_result


def missing(code):
    response = SimpleNamespace(status=404, reason="Not Found")
    return discord.NotFound(response, {"code": code, "message": "Unknown interaction"})


class InteractionRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, *, deferred=False):
        return SimpleNamespace(
            created_at=discord.utils.utcnow() - timedelta(seconds=4),
            guild_id=1, user=SimpleNamespace(id=7, voice=object()),
            response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: deferred),
            followup=SimpleNamespace(send=AsyncMock()),
            channel=SimpleNamespace(send=AsyncMock()),
            command=SimpleNamespace(name="play"),
        )

    async def asyncTearDown(self):
        for view in tuple(bot.music.views):
            view.stop()
        bot.music.views.clear()

    async def test_expired_initial_ack_still_returns_search_menu(self):
        interaction = self.interaction()
        interaction.response.defer.side_effect = missing(10062)
        results = {"entries": [{"id": "dQw4w9WgXcQ", "title": "Example", "duration": 200}]}
        with patch("music.extract", AsyncMock(return_value=results)):
            await bot.bot.tree.get_command("play").callback(interaction, "Example")
        interaction.channel.send.assert_awaited_once()
        view = interaction.channel.send.call_args.kwargs["view"]
        self.assertEqual(view.menu.options[0].label, "Example")

    async def test_valid_followup_uses_interaction(self):
        interaction = self.interaction(deferred=True)
        await send_music_result(interaction, "Example")
        interaction.followup.send.assert_awaited_once()
        self.assertNotIn("view", interaction.followup.send.call_args.kwargs)
        interaction.channel.send.assert_not_awaited()

    async def test_failed_confirmation_still_consumes_selection(self):
        interaction = self.interaction(deferred=True)
        interaction.followup.send.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), "Cannot send message"
        )
        interaction.edit_original_response = AsyncMock()
        music = SimpleNamespace(bot=SimpleNamespace(voice_lock=asyncio.Lock()), enqueue=AsyncMock(), views=set())
        track = Track("Example", "https://youtu.be/dQw4w9WgXcQ", 200)
        view = SearchResults(music, 7, [track])
        with patch.object(type(view.menu), "values", ["0"]), self.assertLogs("capri-anthem.music", "WARNING"):
            await view.choose(interaction)
        music.enqueue.assert_awaited_once_with(interaction, track)
        interaction.followup.send.assert_awaited_once()
        interaction.edit_original_response.assert_awaited_once_with(view=view)
        self.assertTrue(view.selected)
        self.assertTrue(view.menu.disabled)

    async def test_expired_webhook_falls_back_to_channel(self):
        interaction = self.interaction(deferred=True)
        interaction.followup.send.side_effect = missing(10015)
        await send_music_result(interaction, "Example")
        self.assertEqual(interaction.channel.send.call_args.args[0], "Example")

    async def test_other_not_found_errors_are_not_hidden(self):
        interaction = self.interaction()
        interaction.response.defer.side_effect = missing(10003)
        with self.assertRaises(discord.NotFound):
            await acknowledge_play(interaction)

    async def test_expired_ack_error_reply_does_not_fail_again(self):
        interaction = self.interaction()
        await bot.command_error(interaction, missing(10062))
        interaction.channel.send.assert_awaited_once()
        interaction.response.defer.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
