# Builds dist\CockpitPortalSetup.exe in its own virtual environment. Run from anywhere: packaging\build.ps1
# Not "Stop": pip and PyInstaller write ordinary messages to stderr. Exit codes are checked below.
$root = Split-Path $PSScriptRoot
$venv = Join-Path $root "build\venv"
if (-not (Test-Path $venv)) { python -m venv $venv }
$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install --quiet -r (Join-Path $root "requirements.txt") -r (Join-Path $PSScriptRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "pip failed" }
# --windowed: no console window. The openvr package finds its DLL as a file beside it, so it must be collected whole.
& $python -m PyInstaller --noconfirm --onefile --windowed --clean `
    --name CockpitPortalSetup `
    --paths (Join-Path $root "pc") `
    --add-data "$(Join-Path $root 'headset');headset" `
    --add-data "$(Join-Path $root 'LICENSE');." `
    --add-data "$(Join-Path $root 'NOTICE.md');." `
    --collect-all openvr `
    --hidden-import portal_panel `
    --hidden-import setup_wizard `
    --hidden-import cockpit_portal `
    --distpath (Join-Path $root "dist") `
    --workpath (Join-Path $root "build\pyinstaller") `
    --specpath (Join-Path $root "build") `
    (Join-Path $root "pc\app.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Get-Item (Join-Path $root "dist\CockpitPortalSetup.exe") | Select-Object Name, Length
