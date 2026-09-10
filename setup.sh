#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if command -v python3.12 >/dev/null 2>&1; then
    python_bin=python3.12
elif command -v python3 >/dev/null 2>&1; then
    python_bin=python3
else
    echo "Python 3.12 is required." >&2
    exit 1
fi

"$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else "Python 3.12 is required.")'

if [[ ! -x .venv/bin/python ]]; then
    "$python_bin" -m venv .venv
fi

python=.venv/bin/python
"$python" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else "Python 3.12 is required.")'

if command -v nvidia-smi >/dev/null 2>&1; then
    echo "NVIDIA GPU detected. Installing CUDA-enabled PyTorch..."
    "$python" -m pip install --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu128
else
    echo "NVIDIA GPU not detected. Installing CPU PyTorch..."
    "$python" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
fi

"$python" -m pip install -r requirements.txt
"$python" -m pip install --no-deps git+https://github.com/myshell-ai/MeloTTS.git
"$python" -m pip install --no-deps 'qwen-tts==0.1.1'
"$python" -m unidic download

if [[ ! -f .env ]]; then
    cp .env.example .env
fi

"$python" prepare.py
echo "Ready. Set DISCORD_TOKEN in .env, then run ./start.sh."
