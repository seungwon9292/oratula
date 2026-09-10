#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ -n "${WSL_DISTRO_NAME:-}" || "$(uname -r 2>/dev/null)" == *microsoft* ]]; then
    venv_dir="${ORATULA_VENV:-$HOME/.local/share/oratula-qwen/venv}"
else
    venv_dir="${ORATULA_VENV:-.venv}"
fi
venv_python="$venv_dir/bin/python"

if [[ ! -x "$venv_python" ]]; then
    echo "Run ./setup.sh first." >&2
    exit 1
fi

exec "$venv_python" bot.py
