"""Measure cold and warm Qwen latency without connecting to Discord."""
import io
import time
import argparse
import json
import os
import statistics
from unittest.mock import patch

import soundfile as sf
import torch

from core import Preference
from engine import DATA, _MODELS, _synthesize_in_worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["faster", "hybrid"], default="faster")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--text", default="안녕하세요. 디스코드 음성 테스트입니다.")
    args = parser.parse_args()
    model_name = "qwen3-tts-1.7b"
    os.environ["QWEN_TRITON"] = "1" if args.backend == "hybrid" else "0"
    if args.threads:
        torch.set_num_threads(args.threads)
    print(f"CUDA available: {torch.cuda.is_available()}", flush=True)
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"CPU threads: {torch.get_num_threads()}", flush=True)
    preference = Preference(model=model_name, voice="Sohee")
    DATA.mkdir(parents=True, exist_ok=True)
    records = []
    for run in range(args.runs + 1):
        phase = "cold" if run == 0 else f"warm-{run}"
        stages = {}
        def timed(name, fn):
            def wrapped(*a, **kw):
                torch.cuda.synchronize()
                began = time.perf_counter()
                result = fn(*a, **kw)
                torch.cuda.synchronize()
                stages[name] = time.perf_counter() - began
                return result
            return wrapped
        start = time.perf_counter()
        if run:
            import faster_qwen3_tts.generate as generation
            tokenizer = _MODELS[preference.model].model.model.speech_tokenizer
            with patch.object(generation, "fast_generate", timed("tokens_s", generation.fast_generate)), patch.object(tokenizer, "decode", timed("decode_s", tokenizer.decode)):
                audio = _synthesize_in_worker(args.text, preference)
        else:
            audio = _synthesize_in_worker(args.text, preference)
        elapsed = time.perf_counter() - start
        wav, sr = sf.read(io.BytesIO(audio))
        duration = len(wav) / sr
        (DATA / f"sample-{model_name}-{args.backend}-{phase}.wav").write_bytes(audio)
        records.append(dict(phase=phase, elapsed_s=elapsed, audio_s=duration, **stages))
        print(stages, flush=True)
        model = _MODELS[preference.model]
        print(f"{phase}: engine={type(model).__module__}.{type(model).__name__}, "
              f"elapsed={elapsed:.2f}s, audio={duration:.2f}s, "
              f"audio/elapsed={duration / elapsed:.2f}x", flush=True)
    report = dict(model=model_name, backend=args.backend, threads=torch.get_num_threads(), runs=records,
                  warm_mean_s=statistics.mean(r["elapsed_s"] for r in records[1:]))
    (DATA / f"benchmark-{model_name}-{args.backend}-{torch.get_num_threads()}threads.json").write_text(json.dumps(report, indent=2))
    print(f"Warm mean: {report['warm_mean_s']:.3f}s", flush=True)


if __name__ == "__main__":
    main()
