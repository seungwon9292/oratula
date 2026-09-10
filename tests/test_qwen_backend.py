import io
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

import engine
from core import MODEL_VOICES, Preference


class QwenBackendTests(unittest.TestCase):
    def test_hybrid_patches_before_generation_and_reuses_model(self):
        events = []
        model = Mock()
        model.generate_custom_voice.side_effect = lambda **kw: (events.append("generate") or [np.zeros(2400)], 24000)
        factory = Mock()
        factory.from_pretrained.return_value = model
        module = types.ModuleType("qwen3_tts_triton.models.patching")
        module.find_patchable_model = Mock(return_value=model.model)
        module.apply_triton_kernels = Mock(side_effect=lambda *a, **kw: events.append("patch"))
        with patch.dict(engine._MODELS, {}, clear=True), patch.dict(os.environ, {"QWEN_TRITON": "1"}), patch.dict(sys.modules, {module.__name__: module}), patch.object(engine.os, "name", "posix"), patch.object(engine, "_qwen_model_class", return_value=factory), patch.object(engine, "_cached_or_download", return_value="cached") as download, patch("torch.cuda.is_available", return_value=True):
            pref = Preference(model="qwen3-tts-1.7b", voice="Sohee")
            for _ in range(2):
                result = engine._synthesize_in_worker("[기쁘게] 테스트", pref)
                self.assertEqual(sf.info(io.BytesIO(result)).samplerate, 24000)
            self.assertEqual(events, ["patch", "generate", "generate"])
            download.assert_called_once_with("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
            factory.from_pretrained.assert_called_once()
            module.apply_triton_kernels.assert_called_once_with(model.model, patch_range=(0, 24))
            for call in model.generate_custom_voice.call_args_list:
                self.assertEqual(call.kwargs["text"], "테스트")
                self.assertEqual(call.kwargs["instruct"], "기쁘게")

    def test_only_1_7b_is_exposed(self):
        self.assertEqual(len(MODEL_VOICES["qwen3-tts-1.7b"]), 9)
        self.assertNotIn("qwen3-tts-0.6b", MODEL_VOICES)


if __name__ == "__main__":
    unittest.main()
