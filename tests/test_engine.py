import asyncio
import numpy as np
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


class AudioProcessingTests(unittest.TestCase):
    def test_change_tempo_preserves_pitch_and_changes_duration(self):
        sample_rate = 24_000
        time_axis = np.arange(sample_rate, dtype=np.float32) / sample_rate
        wav = np.sin(2 * np.pi * 440 * time_axis).astype(np.float32)

        faster = engine._change_tempo(wav, sample_rate, 1.25)

        self.assertAlmostEqual(len(faster) / sample_rate, 0.8, delta=0.03)
        spectrum = np.abs(np.fft.rfft(faster))
        peak_frequency = np.fft.rfftfreq(len(faster), 1 / sample_rate)[spectrum.argmax()]
        self.assertAlmostEqual(peak_frequency, 440, delta=3)


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
