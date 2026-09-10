#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ -n "${WSL_DISTRO_NAME:-}" || "$(uname -r 2>/dev/null)" == *microsoft* ]]; then
    venv_dir="${ORATULA_VENV:-$HOME/.local/share/oratula-qwen/venv}"
else
    venv_dir="${ORATULA_VENV:-.venv}"
fi
venv_python="$venv_dir/bin/python"

if [[ -x "$venv_python" ]] && "$venv_python" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' 2>/dev/null; then
    python_bin="$venv_python"
elif command -v python3.12 >/dev/null 2>&1; then
    python_bin=python3.12
elif command -v uv >/dev/null 2>&1; then
    echo "System Python 3.12 not found. Installing a managed Python 3.12 with uv..."
    uv python install 3.12
    uv venv --python 3.12 "$venv_dir"
    python_bin="$venv_python"
elif command -v python3 >/dev/null 2>&1; then
    python_bin=python3
else
    echo "Python 3.12 is required." >&2
    exit 1
fi

if ! "$python_bin" -m pip --version >/dev/null 2>&1; then
    if command -v uv >/dev/null 2>&1; then
        echo "pip not found in the virtual environment. Seeding it with uv..."
        uv venv --seed --clear --python 3.12 "$venv_dir"
    else
        "$python_bin" -m ensurepip --upgrade
    fi
    python_bin="$venv_python"
fi

"$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else "Python 3.12 is required.")'

if [[ ! -x "$venv_python" ]]; then
    "$python_bin" -m venv "$venv_dir"
fi

python="$venv_python"
"$python" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else "Python 3.12 is required.")'

if command -v nvidia-smi >/dev/null 2>&1; then
    echo "NVIDIA GPU detected. Installing CUDA-enabled PyTorch..."
    "$python" -m pip install --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu128
else
    echo "NVIDIA GPU not detected. Installing CPU PyTorch..."
    "$python" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
fi

"$python" -m pip install -r requirements.txt

echo "Faster Qwen uses CUDA graphs with SDPA; no FlashAttention build is needed."


if [[ ! -f .env ]]; then
    cp .env.example .env
fi

"$python" prepare.py
echo "Ready. Set DISCORD_TOKEN in .env, then run ./start.sh."
