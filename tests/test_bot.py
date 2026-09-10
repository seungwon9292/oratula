import asyncio
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import MODEL_VOICES, Preference, Store, clean_text, eligible
import bot as module


class CoreTests(unittest.TestCase):
    def test_settings_survive_restart_and_are_per_user(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            store = Store(path)
            chosen = Preference("supertonic-2", "M4", 1.4, False)
            store.put(10, chosen)
            store.close()
            store = Store(path)
            self.assertEqual(store.get(10), chosen)
            self.assertEqual(store.get(11), Preference())
            store.close()

    def test_reject_invalid_setting(self):
        store = Store(":memory:")
        with self.assertRaises(ValueError):
            store.put(1, Preference(model="not-a-model"))
        with self.assertRaises(ValueError):
            store.put(1, Preference(model="mms-tts-kor", voice="F1"))
        store.close()

    def test_new_korean_models_have_their_own_voices(self):
        self.assertEqual(MODEL_VOICES["mms-tts-kor"], ("MMS",))
        self.assertEqual(len(MODEL_VOICES["qwen3-tts-0.6b"]), 9)
        self.assertIn("Sohee", MODEL_VOICES["qwen3-tts-0.6b"])
        self.assertIn("Aiden", MODEL_VOICES["qwen3-tts-0.6b"])

    def test_voice_targets_are_stored_per_guild(self):
        store = Store(":memory:")
        store.set_target(100, 1001)
        store.set_target(200, 2001)
        self.assertEqual(store.get_target(100), 1001)
        self.assertEqual(store.get_target(200), 2001)
        store.clear_target(100)
        self.assertIsNone(store.get_target(100))
        self.assertEqual(store.get_target(200), 2001)
        store.close()

    def test_channel_independent_policy(self):
        args = dict(message_guild=1, session_guild=1, author_is_bot=False,
                    author_voice=50, target_voice=50)
        self.assertTrue(eligible(**args))
        for changes in ({"message_guild": None}, {"message_guild": 2},
                        {"author_is_bot": True}, {"author_voice": None}, {"author_voice": 51}):
            self.assertFalse(eligible(**(args | changes)))

    def test_sanitize_and_limit(self):
        result = clean_text("안녕 ```secret code``` ||spoiler|| https://example.com <:smile:123>")
        self.assertNotIn("secret", result)
        self.assertNotIn("spoiler", result)
        self.assertNotIn("example", result)
        self.assertIn("안녕", result)
        self.assertEqual(len(clean_text("가" * 500)), 300)


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data_patch = patch.object(module, "DATA", Path(self.temp.name))
        self.data_patch.start()
        self.bot = module.TTSBot()
        self.member = NS(id=10, bot=False, voice=NS(channel=NS(id=50)))
        self.voice = NS(channel=NS(id=50), is_connected=lambda: True, stop=lambda: None)
        self.guild = NS(id=1, voice_client=self.voice, get_member=lambda uid: self.member if uid == 10 else None)
        self.session = module.Session(self.guild, 50)
        self.bot.sessions[1] = self.session

    async def asyncTearDown(self):
        if self.session.task:
            self.session.task.cancel()
            await asyncio.gather(self.session.task, return_exceptions=True)
        self.bot.sessions.clear()
        await self.bot.close()
        self.data_patch.stop()
        self.temp.cleanup()

    def message(self, channel=99, text="안녕"):
        return NS(guild=self.guild, author=self.member, channel=NS(id=channel), clean_content=text)

    async def test_all_text_channels_and_threads(self):
        for channel in (99, 101, 9999):
            self.session.last_message.clear()
            await self.bot.on_message(self.message(channel=channel))
        self.assertEqual(self.session.queue.qsize(), 3)

    async def test_outside_voice_and_opt_out_are_ignored(self):
        self.member.voice.channel.id = 51
        await self.bot.on_message(self.message())
        self.member.voice.channel.id = 50
        self.bot.store.put(10, replace(Preference(), enabled=False))
        await self.bot.on_message(self.message())
        self.assertTrue(self.session.queue.empty())

    async def test_flood_and_queue_limit(self):
        await self.bot.on_message(self.message())
        await self.bot.on_message(self.message())
        self.assertEqual(self.session.queue.qsize(), 1)
        for _ in range(40):
            self.session.last_message.clear()
            await self.bot.on_message(self.message())
        self.assertEqual(self.session.queue.qsize(), 30)

    async def test_leave_during_synthesis_never_plays(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        async def synthesize(*args):
            entered.set()
            await resume.wait()
            return b"audio"
        self.bot.engine.synthesize = synthesize
        self.session.task = asyncio.create_task(self.bot.worker(self.session))
        await self.bot.on_message(self.message())
        await asyncio.wait_for(entered.wait(), 2)
        self.member.voice.channel.id = 51
        resume.set()
        await asyncio.wait_for(self.session.queue.join(), 2)
        self.assertIsNone(self.session.last_error)

    async def test_clear_during_synthesis_never_plays(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        async def synthesize(*args):
            entered.set()
            await resume.wait()
            return b"audio"
        self.bot.engine.synthesize = synthesize
        self.session.task = asyncio.create_task(self.bot.worker(self.session))
        await self.bot.on_message(self.message())
        await asyncio.wait_for(entered.wait(), 2)
        self.session.clear()
        resume.set()
        await asyncio.wait_for(self.session.queue.join(), 2)
        self.assertIsNone(self.session.last_error)

    async def test_error_does_not_kill_worker(self):
        self.bot.engine.synthesize = AsyncMock(side_effect=RuntimeError("unavailable"))
        self.session.task = asyncio.create_task(self.bot.worker(self.session))
        await self.bot.on_message(self.message())
        await asyncio.wait_for(self.session.queue.join(), 2)
        self.assertEqual(self.session.last_error, "RuntimeError")
        self.assertFalse(self.session.task.done())

    async def test_commands_build_without_discord_token(self):
        module.register_commands(self.bot)
        commands = self.bot.tree.get_commands()
        self.assertEqual(len(commands), 6)
        for command in commands:
            command.to_dict(self.bot.tree)
        voice_command = next(command for command in commands if command.name == "oratula-voice")
        payload = voice_command.to_dict(self.bot.tree)
        voice_option = next(option for option in payload["options"] if option["name"] == "voice")
        self.assertTrue(voice_option["autocomplete"])
        self.assertNotIn("choices", voice_option)

    async def test_disconnected_session_rejoins_on_next_message(self):
        self.voice.is_connected = lambda: False
        self.bot.store.set_target(1, 50)
        channel = NS(id=50)
        self.guild.get_channel = lambda cid: channel
        async def reconnect(*args):
            self.voice.is_connected = lambda: True
            return self.session
        self.bot.ensure_session = AsyncMock(side_effect=reconnect)
        with patch.object(module.discord, "VoiceChannel", type(channel)):
            await self.bot.on_message(self.message())
        self.bot.ensure_session.assert_awaited_once_with(self.guild, channel)
        self.assertEqual(self.session.queue.qsize(), 1)

    async def test_stopped_target_cannot_rejoin_from_pending_message(self):
        channel = NS(id=50, connect=AsyncMock())
        result = await self.bot.ensure_session(self.guild, channel)
        self.assertIsNone(result)
        channel.connect.assert_not_awaited()

    async def test_next_message_waits_for_previous_playback(self):
        played = asyncio.Event()
        callbacks = []
        def play(source, *, after):
            callbacks.append(after)
            played.set()
        self.voice.play = play
        self.bot.engine.synthesize = AsyncMock(return_value=b"audio")
        with patch.object(module.discord, "FFmpegOpusAudio"):
            self.session.task = asyncio.create_task(self.bot.worker(self.session))
            self.session.queue.put_nowait(module.Utterance(10, "first"))
            self.session.queue.put_nowait(module.Utterance(10, "second"))
            await asyncio.wait_for(played.wait(), 2)
            self.assertEqual(self.bot.engine.synthesize.await_count, 1)
            played.clear()
            callbacks[0](None)
            await asyncio.wait_for(played.wait(), 2)
            self.assertEqual(self.bot.engine.synthesize.await_args.args[0], "second")
            callbacks[1](None)
            await asyncio.wait_for(self.session.queue.join(), 2)


if __name__ == "__main__":
    unittest.main()
