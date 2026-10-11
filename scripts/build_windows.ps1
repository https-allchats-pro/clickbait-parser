# Build Windows ClickbaitParser → dist/release/*.zip
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}
& $Python scripts/build_release.py --os windows --clean @args
exit $LASTEXITCODE
