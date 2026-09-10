$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Test-Python312 {
    param([string]$Executable, [string[]]$PrefixArguments = @())
    if (-not $Executable) { return $false }
    & $Executable @PrefixArguments -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

$venvPython = '.venv\Scripts\python.exe'
$venvExists = Test-Path -LiteralPath $venvPython
if (-not $venvExists -or -not (Test-Python312 $venvPython)) {
    $pythonExecutable = $null
    $pythonPrefixArguments = @()
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue

    if ($pyLauncher -and (Test-Python312 $pyLauncher.Source @('-3.12'))) {
        $pythonExecutable = $pyLauncher.Source
        $pythonPrefixArguments = @('-3.12')
    } elseif ($pythonCommand -and (Test-Python312 $pythonCommand.Source)) {
        $pythonExecutable = $pythonCommand.Source
    } else {
        throw 'Install Python 3.12 and rerun setup.ps1.'
    }

    if (-not $venvExists) {
        & $pythonExecutable @pythonPrefixArguments -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed. Install Python 3.12.' }
    } else {
        Write-Host 'Repairing virtual environment after its Python installation changed...'
        & $pythonExecutable @pythonPrefixArguments -m venv --upgrade .venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Python312 $venvPython)) {
            throw 'Virtual environment repair failed. Rename or remove .venv, then rerun setup.ps1.'
        }
    }
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
