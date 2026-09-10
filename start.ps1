$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw 'Run setup.ps1 first.'
}
& .\.venv\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3, 12)" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'The virtual environment is broken or is not Python 3.12. Run setup.ps1 to repair it.'
}
& .\.venv\Scripts\python.exe bot.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
