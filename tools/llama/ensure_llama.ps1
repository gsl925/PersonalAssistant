# Makes sure llama-swap is answering on the given port: does nothing if it already is,
# otherwise starts it (in its own console window, like start_all.bat does) and waits
# until it responds. Safe to call from any project's start script - the one shared
# server serves every project on this machine, so never start a second copy by hand.
#
#   powershell -ExecutionPolicy Bypass -File <this repo>\tools\llama\ensure_llama.ps1
#   powershell -ExecutionPolicy Bypass -File <this repo>\tools\llama\ensure_llama.ps1 -Port 8090 -TimeoutSec 120
#
# Exit code 0 = ready, 1 = did not come up in time (look at the llama-swap window).
param(
    [int]$Port = 8090,
    [int]$TimeoutSec = 120
)

$ErrorActionPreference = "Stop"
$url = "http://127.0.0.1:$Port/v1/models"

function Test-LlamaSwap {
    try { Invoke-RestMethod $url -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

if (Test-LlamaSwap) {
    Write-Host "llama-swap already running on :$Port"
    exit 0
}

$bat = Join-Path $PSScriptRoot "start_llama.bat"
$env:LLAMA_SWAP_PORT = "$Port"   # child console inherits it
Write-Host "Starting llama-swap on :$Port ..."
Start-Process cmd.exe -ArgumentList "/k", "`"$bat`""

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    if (Test-LlamaSwap) {
        Write-Host "llama-swap is up on :$Port"
        exit 0
    }
    Start-Sleep -Seconds 1
}
Write-Host "llama-swap did not answer on :$Port within $TimeoutSec s - check its console window."
exit 1
