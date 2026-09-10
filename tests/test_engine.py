import asyncio
import os
import time
import unittest
from unittest.mock import patch

from core import Preference
import engine


def fake_synthesis(text, preference):
    if text == "hang":
        time.sleep(30)
    if text == "crash":
        os._exit(1)
    return b"audio"


class EngineRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_replaces_worker_and_next_request_succeeds(self):
        worker = engine.Engine(timeout=0.5)
        try:
            with patch.object(engine, "_synthesize_in_worker", fake_synthesis):
                with self.assertRaises(TimeoutError):
                    await worker.synthesize("hang", Preference())
                worker.timeout = 10
                self.assertEqual(await worker.synthesize("next", Preference()), b"audio")
        finally:
            worker.close()

    async def test_process_crash_recovers(self):
        worker = engine.Engine(timeout=10)
        try:
            with patch.object(engine, "_synthesize_in_worker", fake_synthesis):
                with self.assertRaises(engine.BrokenProcessPool):
                    await worker.synthesize("crash", Preference())
                self.assertEqual(await worker.synthesize("next", Preference()), b"audio")
        finally:
            worker.close()

    async def test_cancellation_does_not_block_next_request(self):
        worker = engine.Engine(timeout=10)
        try:
            with patch.object(engine, "_synthesize_in_worker", fake_synthesis):
                task = asyncio.create_task(worker.synthesize("hang", Preference()))
                await asyncio.sleep(0.3)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual(await worker.synthesize("next", Preference()), b"audio")
        finally:
            worker.close()
