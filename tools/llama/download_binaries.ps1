# Downloads the llama.cpp CUDA build and llama-swap into tools\llama\bin\ (gitignored).
# Portable zips only - nothing is installed or registered with Windows.
#
# Re-run with different tags to update; the old folders are replaced.
#   powershell -ExecutionPolicy Bypass -File tools\llama\download_binaries.ps1
#   powershell -ExecutionPolicy Bypass -File tools\llama\download_binaries.ps1 -LlamaCppTag b12300 -Cuda 12.4
param(
    [string]$LlamaCppTag = "b12242",
    [string]$LlamaSwapTag = "v271",
    # 13.5 is the build that targets Blackwell (RTX 50xx); use 12.4 only as a fallback.
    [string]$Cuda = "13.5"
)

$ErrorActionPreference = "Stop"
$bin = Join-Path $PSScriptRoot "bin"
$dl = Join-Path $bin "_downloads"
New-Item -ItemType Directory -Force $dl | Out-Null

function Get-File($url, $dest) {
    if (Test-Path $dest) { Write-Host "  already downloaded: $dest"; return }
    Write-Host "  $url"
    # curl.exe resumes (-C -) and fails on HTTP errors (--fail); both matter for 400+ MB files.
    & curl.exe -L --fail -C - -o "$dest.part" $url
    if ($LASTEXITCODE -ne 0) { throw "download failed: $url" }
    Move-Item "$dest.part" $dest
}

function Expand-Fresh($zip, $target, [switch]$Merge) {
    if ((Test-Path $target) -and -not $Merge) { Remove-Item -Recurse -Force $target }
    Expand-Archive -Path $zip -DestinationPath $target -Force
}

$llamaBase = "https://github.com/ggml-org/llama.cpp/releases/download/$LlamaCppTag"
$llamaZip = "llama-$LlamaCppTag-bin-win-cuda-$Cuda-x64.zip"
$cudartZip = "cudart-llama-bin-win-cuda-$Cuda-x64.zip"

Write-Host "llama.cpp $LlamaCppTag (CUDA $Cuda)"
Get-File "$llamaBase/$llamaZip" (Join-Path $dl $llamaZip)
Get-File "$llamaBase/$cudartZip" (Join-Path $dl $cudartZip)
$llamaDir = Join-Path $bin "llama.cpp"
Expand-Fresh (Join-Path $dl $llamaZip) $llamaDir
# The CUDA runtime DLLs go next to llama-server.exe so no CUDA toolkit install is needed.
Expand-Fresh (Join-Path $dl $cudartZip) $llamaDir -Merge

$swapNum = $LlamaSwapTag.TrimStart("v")
$swapZip = "llama-swap_${swapNum}_windows_amd64.zip"
Write-Host "llama-swap $LlamaSwapTag"
Get-File "https://github.com/mostlygeek/llama-swap/releases/download/$LlamaSwapTag/$swapZip" (Join-Path $dl $swapZip)
Expand-Fresh (Join-Path $dl $swapZip) (Join-Path $bin "llama-swap")

Write-Host ""
Write-Host "Done. Check the GPU is visible:"
Write-Host "  tools\llama\bin\llama.cpp\llama-server.exe --list-devices"
