# Sets up model-bench on this machine. Run it once after cloning, and again
# whenever uv.lock changes. Everything (uv's cache, Python, the environment)
# goes inside this folder; nothing else on the computer changes.
#
#     .\setup.ps1              install, or bring up to date
#     .\setup.ps1 -Reinstall   reinstall every package

param([switch]$Reinstall)
$repo = $PSScriptRoot

function Fail($message) {
    Write-Host "`nSTOP: $message" -ForegroundColor Red
    exit 1
}

Write-Host "== Checking tools"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail "uv is not installed. Install it with: winget install astral-sh.uv   (then open a new terminal)"
}
$uvVersion = ((uv --version) -split " ")[1]
$v = [version]$uvVersion
if ($v -lt [version]"0.11.26" -or $v -ge [version]"0.12") {
    Fail "uv is $uvVersion; this project is locked with uv 0.11.x (0.11.26 or newer). Run: uv self update 0.11.26"
}
Write-Host "  uv: $uvVersion"

$env:UV_CACHE_DIR = Join-Path $repo ".uv\cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repo ".uv\python"
$env:UV_LINK_MODE = "copy"
$env:UV_PYTHON_PREFERENCE = "only-managed"

Write-Host "`n== Installing (uv sync --locked)"
Push-Location $repo
try {
    $syncArgs = @("sync", "--locked")
    if ($Reinstall) { $syncArgs += "--reinstall" }
    & uv @syncArgs
    if ($LASTEXITCODE -ne 0) { Fail "uv sync failed; the lines above say why." }
    & uv run --locked --no-sync python -c "import PySide6, yaml, psutil; print('  PySide6', PySide6.__version__)"
    if ($LASTEXITCODE -ne 0) { Fail "the installed packages don't import; run .\setup.ps1 -Reinstall" }
}
finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $repo "machine.yaml"))) {
    Write-Host "`nNext: copy machine.example.yaml to machine.yaml and set the paths in it." -ForegroundColor Yellow
}
Write-Host "`nOK. model-bench is set up. Open it with: .\bench.ps1" -ForegroundColor Green
