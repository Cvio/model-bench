# model-bench: an end-to-end test bench for volis configurations.
#
#     .\bench.ps1                     open the window
#     .\bench.ps1 start --no-window   run the queue without the window
#     .\bench.ps1 pause               finish the current job, then stop
#     .\bench.ps1 stop                stop at once (the running job runs again later)
#     .\bench.ps1 status              counts, what's running, the last log lines
#     .\bench.ps1 retry-failed        put failed jobs back in the queue
#
# Not "$ErrorActionPreference = Stop": Windows PowerShell 5.1 turns a program's
# stderr into an error when output is redirected. The exit code decides.
$repo = $PSScriptRoot
if (-not (Test-Path (Join-Path $repo ".venv"))) {
    Write-Host "STOP: this folder isn't set up yet. Run .\setup.ps1 first." -ForegroundColor Red
    exit 1
}
Push-Location $repo
try {
    & uv run --locked --no-sync python -m bench.cli @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
