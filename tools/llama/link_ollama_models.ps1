# Reuses models already pulled into Ollama: creates hard links to their GGUF blobs under readable
# names in the shared model folder. No extra disk space, nothing is copied or modified in the Ollama
# store, and the data stays even if Ollama later removes the model (a hard link keeps it alive).
#
# Needs the Ollama store and the destination on the SAME drive (hard links cannot cross drives).
# Only models llama.cpp can load are listed. qwen3-vl:8b and gemma4:26b are NOT: Ollama's newer
# engine writes its own tensor layout - get those with download_models.ps1.
#
#   powershell -ExecutionPolicy Bypass -File tools\llama\link_ollama_models.ps1 -OllamaDir D:\OllamaModels
param(
    # The folder that contains Ollama's "blobs" and "manifests" (its OLLAMA_MODELS setting).
    [string]$OllamaDir = $env:OLLAMA_MODELS,
    [string]$Dest = ""
)

$ErrorActionPreference = "Stop"
if (-not $OllamaDir) { throw "Pass -OllamaDir <folder containing Ollama's blobs and manifests>." }
. (Join-Path $PSScriptRoot "_common.ps1")
$dest = Get-ModelsDir $Dest

# manifest = <model>/<tag> under manifests\registry.ollama.ai\library; kind = layer to link.
$links = @(
    @{ manifest = "qwen3/8b";            kind = "model";     out = "Qwen3-8B-Q4_K_M.gguf" },
    @{ manifest = "deepseek-r1/14b";     kind = "model";     out = "DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf" },
    @{ manifest = "bge-m3/latest";       kind = "model";     out = "bge-m3-F16.gguf" },
    @{ manifest = "minicpm-v/8b";        kind = "model";     out = "minicpm-v-2_6.gguf" },
    @{ manifest = "minicpm-v/8b";        kind = "projector"; out = "minicpm-v-2_6-mmproj-f16.gguf" }
)

New-Item -ItemType Directory -Force $dest | Out-Null
$dest = (Resolve-Path $dest).Path
Write-Host "Ollama store: $OllamaDir"
Write-Host "Destination:  $dest"

foreach ($l in $links) {
    $target = Join-Path $dest $l.out
    if (Test-Path $target) { Write-Host "have $($l.out)"; continue }
    $manifestPath = Join-Path $OllamaDir "manifests\registry.ollama.ai\library\$($l.manifest -replace '/', '\')"
    if (-not (Test-Path $manifestPath)) { Write-Host "skip $($l.manifest): not pulled in Ollama"; continue }
    $layer = (Get-Content $manifestPath -Raw | ConvertFrom-Json).layers |
        Where-Object { $_.mediaType -like "*.$($l.kind)" } | Select-Object -First 1
    $blob = Join-Path $OllamaDir ("blobs\" + ($layer.digest -replace ":", "-"))
    if (-not (Test-Path $blob)) { Write-Host "skip $($l.manifest): blob missing"; continue }
    New-Item -ItemType HardLink -Path $target -Target $blob | Out-Null
    Write-Host "linked $($l.out)  <-  $($l.manifest) ($([math]::Round($layer.size / 1GB, 2)) GB)"
}
Write-Host "Done."
