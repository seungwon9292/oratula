#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ -n "${WSL_DISTRO_NAME:-}" || "$(uname -r 2>/dev/null)" == *microsoft* ]]; then
    venv_dir="${ORATULA_VENV:-$HOME/.local/share/oratula/venv}"
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
"$python" -m pip install --no-deps git+https://github.com/myshell-ai/MeloTTS.git
"$python" -m pip install --no-deps 'qwen-tts==0.1.1'

if [[ "${ORATULA_INSTALL_FLASH_ATTN:-0}" != "1" ]]; then
    echo "Skipping optional FlashAttention install; Qwen will use the SDPA backend."
elif command -v nvcc >/dev/null 2>&1; then
    compiler_major=""
    if command -v g++ >/dev/null 2>&1; then
        compiler_major="$(g++ -dumpversion | cut -d. -f1)"
    fi
    if [[ "$compiler_major" =~ ^[0-9]+$ ]] && (( compiler_major >= 14 )); then
        echo "CUDA toolkit found, but g++ $compiler_major is incompatible with CUDA 12.4 (requires <14)."
        echo "Install g++-13 to enable FlashAttention; Qwen will use the SDPA fallback for now."
    else
        echo "CUDA toolkit detected. Installing FlashAttention 2 for faster Qwen inference..."
        export PATH="$venv_dir/bin:$PATH"
        export CC="${CC:-$(command -v gcc || true)}"
        export CXX="${CXX:-$(command -v g++ || true)}"
        export CUDAHOSTCXX="${CUDAHOSTCXX:-$CXX}"
        "$python" -m pip install ninja packaging psutil
        if ! "$python" -m pip install -U flash-attn --no-build-isolation; then
            echo "Warning: FlashAttention installation failed; Qwen will use SDPA fallback." >&2
        fi
    fi
else
    echo "CUDA toolkit (nvcc) not found; Qwen will use the SDPA fallback."
fi

"$python" -m unidic download

if [[ ! -f .env ]]; then
    cp .env.example .env
fi

"$python" prepare.py
echo "Ready. Set DISCORD_TOKEN in .env, then run ./start.sh."
