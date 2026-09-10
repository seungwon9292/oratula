"""Download selected models and produce a Korean smoke-test WAV for each."""
import argparse
import asyncio
from core import MODEL_VOICES, MODELS, Preference
from engine import Engine, DATA


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    # Initial weight downloads can take longer than the live inference limit.
    engine = Engine(timeout=1800)
    try:
        for model in args.models:
            print(f"Preparing {model}...", flush=True)
            preference = Preference(model=model, voice=MODEL_VOICES[model][0], speed=1.0)
            data = await engine.synthesize("안녕하세요. 디스코드 음성 테스트입니다.", preference)
            path = DATA / f"sample-{model}.wav"
            path.write_bytes(data)
            print(f"OK: {path}", flush=True)
    finally:
        engine.close()


if __name__ == "__main__":
    asyncio.run(main())
