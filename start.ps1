param(
    [string]$Distro = 'Ubuntu',
    [switch]$Windows
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not $Windows) {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        throw 'WSL2 is not installed. Install it with: wsl --install'
    }
    $pathConversionFailed = $false
    if ($PSScriptRoot -match '^([A-Za-z]):\\') {
        $drive = $matches[1].ToLowerInvariant()
        $relativePath = $PSScriptRoot.Substring(3).Replace('\', '/')
        $linuxRoot = "/mnt/$drive/$relativePath"
    } else {
        try {
            $linuxRoot = (& wsl.exe -d $Distro -- wslpath -a $PSScriptRoot 2>$null | Out-String).Trim()
        } catch {
            $linuxRoot = ''
            $pathConversionFailed = $true
        }
    }
    if ($pathConversionFailed -or -not $linuxRoot) {
        throw "WSL distribution '$Distro' is unavailable. Install it or pass -Distro with its name."
    }
    & wsl.exe -d $Distro -- bash -lc "cd '$linuxRoot' && exec bash ./start.sh"
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw 'Run setup.ps1 first.'
}
& .\.venv\Scripts\python.exe -c "import sys; assert sys.version_info[:2] == (3, 12)" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'The virtual environment is broken or is not Python 3.12. Run setup.ps1 to repair it.'
}
& .\.venv\Scripts\python.exe bot.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
