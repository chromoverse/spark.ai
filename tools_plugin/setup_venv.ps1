param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root ".venv"

if (-not (Test-Path $venv)) {
    & $Python -m venv $venv
}

$activate = Join-Path $venv "Scripts\\Activate.ps1"
. $activate

python -m pip install --upgrade pip
python -m pip install -r (Join-Path $root "requirements.txt")

Write-Host "tools_plugin venv ready: $venv"
