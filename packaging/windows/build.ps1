# Build the Windows installer: packaging\build\installer\DeskDot-Setup-<version>-x64.exe
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1 [-SkipStudio] [-SkipInstaller]
#
# Uses its own environment (packaging\build\venv), so the .venv you develop with is never touched.
# Needs: uv, Node (unless -SkipStudio and web\dist exists), Inno Setup 6 (iscc) for the installer step.
param([switch]$SkipStudio, [switch]$SkipInstaller)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $root

if (-not $SkipStudio) {
    Push-Location web
    npm run build
    if ($LASTEXITCODE) { throw "studio build failed" }
    Pop-Location
}

$env:UV_PROJECT_ENVIRONMENT = Join-Path $root "packaging\build\venv"
uv sync --frozen --no-dev --extra launcher --group packaging
if ($LASTEXITCODE) { throw "uv sync failed" }
$version = (uv run --no-sync python packaging\prepare.py | Select-Object -Last 1).Trim()
Write-Host "DeskDot $version"

uv run --no-sync pyinstaller packaging\deskdot.spec --noconfirm --clean `
    --distpath packaging\build\dist --workpath packaging\build\work
if ($LASTEXITCODE) { throw "pyinstaller failed" }

if ($SkipInstaller) { return }
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                 "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
    if (-not $iscc -and (Test-Path $c)) { $iscc = $c }
}
if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
& $iscc "/DAppVersion=$version" packaging\windows\DeskDot.iss
if ($LASTEXITCODE) { throw "iscc failed" }
Get-Item "packaging\build\installer\DeskDot-Setup-$version-x64.exe"
