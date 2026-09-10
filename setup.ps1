$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv .venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .venv
    } elseif (Test-Path -LiteralPath $bundledPython) {
        & $bundledPython -m venv .venv
    } else {
        throw 'Install Python 3.12 and rerun setup.ps1.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed. Install Python 3.12.' }
}
& .\.venv\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3, 12), 'Python 3.12 is required.'"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Write-Host 'NVIDIA GPU detected. Installing CUDA-enabled PyTorch...'
    & .\.venv\Scripts\python.exe -m pip install --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu128
} else {
    Write-Host 'NVIDIA GPU not detected. Installing CPU PyTorch...'
    & .\.venv\Scripts\python.exe -m pip install torch torchaudio
}
if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed.' }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& .\.venv\Scripts\python.exe -m pip install --no-deps git+https://github.com/myshell-ai/MeloTTS.git
if ($LASTEXITCODE -ne 0) { throw 'MeloTTS installation failed.' }
& .\.venv\Scripts\python.exe -m pip install --no-deps 'qwen-tts==0.1.1'
if ($LASTEXITCODE -ne 0) { throw 'Qwen3-TTS installation failed.' }
& .\.venv\Scripts\python.exe -m unidic download
if ($LASTEXITCODE -ne 0) { throw 'MeCab dictionary installation failed.' }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
& .\.venv\Scripts\python.exe prepare.py
if ($LASTEXITCODE -ne 0) { throw 'Model preparation failed. Check internet connection and retry.' }
Write-Host 'Ready. Set DISCORD_TOKEN in .env, then run start.ps1.'
