"""Cached local TTS models, isolated from the Discord event loop."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import redirect_stdout
import io
import multiprocessing
from pathlib import Path
import os
import shutil
import subprocess
import warnings

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
# Keep all automatically downloaded assets inside the project.
os.environ.setdefault("HF_HOME", str(DATA / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
warnings.filterwarnings(
    "ignore",
    message=r".*torch\.nn\.utils\.weight_norm.*deprecated.*",
    category=FutureWarning,
)


_MODELS = {}
_STYLES = {}


def _qwen_model_class():
    """Import Qwen without probing optional SoX support used only by 25 Hz models."""
    import sys
    from types import ModuleType

    previous_sox_module = sys.modules.get("sox")
    if shutil.which("sox") is None:
        optional_sox = ModuleType("sox")

        class UnavailableTransformer:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("SoX is required only for Qwen 25 Hz voice cloning")

        optional_sox.Transformer = UnavailableTransformer
        sys.modules["sox"] = optional_sox

    try:
        # qwen-tts imports its unused 25 Hz tokenizer eagerly. It prints SoX and
        # flash-attn warnings even though this project uses the 12 Hz model with SDPA.
        with redirect_stdout(io.StringIO()):
            import qwen_tts  # Load its optional tokenizer imports under the SoX guard.
            from faster_qwen3_tts import FasterQwen3TTS as Qwen3TTSModel
    finally:
        if previous_sox_module is None:
            sys.modules.pop("sox", None)
        else:
            sys.modules["sox"] = previous_sox_module
    return Qwen3TTSModel


def _change_tempo(wav, sample_rate, speed):
    """Change speaking rate with FFmpeg's speech-friendly, pitch-preserving filter."""
    import imageio_ffmpeg
    import numpy as np

    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner", "-loglevel", "error",
        "-f", "f32le", "-ar", str(sample_rate), "-ac", "1", "-i", "pipe:0",
        "-filter:a", f"atempo={speed:.6f}",
        "-f", "f32le", "-ar", str(sample_rate), "-ac", "1", "pipe:1",
    ]
    result = subprocess.run(
        command,
        input=np.asarray(wav, dtype="<f4").tobytes(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype="<f4").copy()


def _cached_or_download(repo_id):
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    required = ["config.json", "model.safetensors", "tokenizer_config.json", "vocab.json"]
    if repo_id.startswith("Qwen/"):
        required += ["merges.txt", "preprocessor_config.json", "generation_config.json",
                     "speech_tokenizer/config.json", "speech_tokenizer/model.safetensors",
                     "speech_tokenizer/preprocessor_config.json"]
    try:
        cached = snapshot_download(repo_id, local_files_only=True)
        if all((Path(cached) / name).is_file() for name in required):
            return cached
    except LocalEntryNotFoundError:
        pass
    return snapshot_download(repo_id, allow_patterns=required)


def _synthesize_in_worker(text, preference):
    """Run imports, model loading, and inference outside the Discord process."""
    import soundfile as sf

    if preference.model == "mms-tts-kor":
        import torch
        from transformers import VitsModel, VitsTokenizer

        if preference.model not in _MODELS:
            model_path = _cached_or_download("facebook/mms-tts-kor")
            tokenizer = VitsTokenizer.from_pretrained(model_path)
            model = VitsModel.from_pretrained(model_path)
            model.eval()
            _MODELS[preference.model] = (tokenizer, model)
        tokenizer, model = _MODELS[preference.model]
        model.speaking_rate = preference.speed
        inputs = tokenizer(text=text, return_tensors="pt")
        with torch.inference_mode():
            wav = model(**inputs).waveform[0].cpu().numpy()
        result = io.BytesIO()
        sf.write(result, wav, model.config.sampling_rate, format="WAV", subtype="PCM_16")
        return result.getvalue()

    if preference.model in ("qwen3-tts-0.6b", "qwen3-tts-1.7b"):
        import numpy as np
        import torch
        Qwen3TTSModel = _qwen_model_class()

        if preference.model not in _MODELS:
            use_cuda = torch.cuda.is_available()
            if not use_cuda:
                raise RuntimeError("Faster Qwen requires CUDA. Select Supertonic or MMS for CPU synthesis.")
            model_path = _cached_or_download(
                "Qwen/Qwen3-TTS-12Hz-" + ("1.7B" if preference.model.endswith("1.7b") else "0.6B") + "-CustomVoice"
            )
            loaded_model = Qwen3TTSModel.from_pretrained(
                model_path,
                device="cuda:0",
                dtype=torch.bfloat16 if use_cuda else torch.float32,
                attn_implementation="sdpa",
            )
            if preference.model.endswith("1.7b") and os.getenv("QWEN_TRITON", "1") == "1" and os.name != "nt":
                from qwen3_tts_triton.models.patching import apply_triton_kernels, find_patchable_model
                # Patch before the first generation captures CUDA graphs.
                internal = find_patchable_model(loaded_model.model)
                apply_triton_kernels(internal, patch_range=(0, 24))
            _MODELS[preference.model] = loaded_model
        model = _MODELS[preference.model]
        wavs, sample_rate = model.generate_custom_voice(
            text=text,
            language="Korean",
            speaker=preference.voice,
            max_new_tokens=1024,
        )
        wav = np.asarray(wavs[0], dtype=np.float32)
        if abs(preference.speed - 1.0) > 0.01:
            wav = _change_tempo(wav, sample_rate, preference.speed)
        result = io.BytesIO()
        sf.write(result, wav, sample_rate, format="WAV", subtype="PCM_16")
        return result.getvalue()

    from supertonic import TTS
    if preference.model not in _MODELS:
        inference_threads = int(os.getenv("SUPERTONIC_INTRA_OP_THREADS", "8"))
        _MODELS[preference.model] = TTS(
            model=preference.model,
            model_dir=str(DATA / "models" / preference.model),
            auto_download=True,
            intra_op_num_threads=max(1, inference_threads),
            inter_op_num_threads=1,
        )
    model = _MODELS[preference.model]
    style_key = (preference.model, preference.voice)
    if style_key not in _STYLES:
        _STYLES[style_key] = model.get_voice_style(voice_name=preference.voice)
    style = _STYLES[style_key]
    total_steps = max(1, int(os.getenv("SUPERTONIC_TOTAL_STEPS", "5")))
    wav, _ = model.synthesize(text, voice_style=style, lang="ko",
                              speed=preference.speed, total_steps=total_steps)
    result = io.BytesIO()
    sf.write(result, wav.reshape(-1), model.sample_rate, format="WAV", subtype="PCM_16")
    return result.getvalue()


class Engine:
    def __init__(self, timeout=120):
        self.timeout = timeout
        self.closed = False
        self.locks = {kind: asyncio.Lock() for kind in ("cpu", "gpu")}
        self.pools = {
            kind: self._new_pool() for kind in ("cpu", "gpu")
        }

    @staticmethod
    def _new_pool():
        return ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn")
        )

    @staticmethod
    def _terminate(pool):
        # Python 3.12 has no public terminate_workers API. Capture owned
        # children before shutdown clears the executor's process registry.
        processes = list((pool._processes or {}).values())
        for process in processes:
            if process.is_alive():
                process.terminate()
        pool.shutdown(wait=False, cancel_futures=True)

    async def synthesize(self, text, preference):
        loop = asyncio.get_running_loop()
        kind = "gpu" if preference.model in ("qwen3-tts-0.6b", "qwen3-tts-1.7b") else "cpu"
        async with self.locks[kind]:
            if self.closed:
                raise RuntimeError("TTS engine is closed")
            pool = self.pools[kind]
            try:
                return await asyncio.wait_for(loop.run_in_executor(
                    pool, _synthesize_in_worker, text, preference
                ), timeout=self.timeout)
            except (TimeoutError, BrokenProcessPool, asyncio.CancelledError):
                self._terminate(pool)
                if not self.closed:
                    self.pools[kind] = self._new_pool()
                raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        for pool in self.pools.values():
            self._terminate(pool)
