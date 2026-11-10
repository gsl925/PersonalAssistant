# Downloads GGUF models. Large files: ~44 GB for everything.
# Destination, in order: -Dest, LLM_MODELS_DIR (environment variable or the repo's .env),
# then data\llm_models\ inside this repo (gitignored).
# Resumable - re-run the same command if a download is interrupted.
#
#   powershell -ExecutionPolicy Bypass -File tools\llama\download_models.ps1            # list models
#   powershell -ExecutionPolicy Bypass -File tools\llama\download_models.ps1 -Only qwen3:8b,bge-m3
#   powershell -ExecutionPolicy Bypass -File tools\llama\download_models.ps1 -All
param(
    [string[]]$Only = @(),
    [switch]$All,
    [string]$Dest = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$dest = Get-ModelsDir $Dest

# id = the model name used in llama-swap.yaml / the capability tiers.
# Sizes are the Hugging Face file sizes (checked 2026-11-10).
$files = @(
    @{ id = "qwen3:8b";         repo = "Qwen/Qwen3-8B-GGUF";                         file = "Qwen3-8B-Q4_K_M.gguf";                        out = "Qwen3-8B-Q4_K_M.gguf";                        gb = 5.03 },
    @{ id = "deepseek-r1:14b";  repo = "bartowski/DeepSeek-R1-Distill-Qwen-14B-GGUF"; file = "DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf";    out = "DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf";    gb = 8.99 },
    @{ id = "gemma4:26b";       repo = "unsloth/gemma-4-26B-A4B-it-GGUF";            file = "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf";           out = "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf";           gb = 16.95 },
    @{ id = "qwen3-vl:8b";      repo = "Qwen/Qwen3-VL-8B-Instruct-GGUF";             file = "Qwen3VL-8B-Instruct-Q4_K_M.gguf";             out = "Qwen3VL-8B-Instruct-Q4_K_M.gguf";            gb = 5.03 },
    @{ id = "qwen3-vl:8b";      repo = "Qwen/Qwen3-VL-8B-Instruct-GGUF";             file = "mmproj-Qwen3VL-8B-Instruct-F16.gguf";         out = "mmproj-Qwen3VL-8B-Instruct-F16.gguf";         gb = 1.16 },
    @{ id = "minicpm-v:8b";     repo = "openbmb/MiniCPM-V-2_6-gguf";                 file = "ggml-model-Q4_K_M.gguf";                      out = "minicpm-v-2_6.gguf";                              gb = 4.68 },
    @{ id = "minicpm-v:8b";     repo = "openbmb/MiniCPM-V-2_6-gguf";                 file = "mmproj-model-f16.gguf";                       out = "minicpm-v-2_6-mmproj-f16.gguf";               gb = 1.04 },
    @{ id = "qwen3-coder:30b";  repo = "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF";  file = "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf";    out = "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf";    gb = 18.56 },
    @{ id = "bge-m3";          repo = "lm-kit/bge-m3-gguf";                         file = "bge-m3-F16.gguf";                             out = "bge-m3-F16.gguf";                             gb = 1.16 }
)

$selected = if ($All) { $files } else { $files | Where-Object { $Only -contains $_.id } }

if (-not $selected) {
    Write-Host "Models (use -Only <id>,<id> or -All):"
    $files | Group-Object { $_.id } | ForEach-Object {
        $total = ($_.Group | Measure-Object -Property gb -Sum).Sum
        "{0,-18} {1,6:N2} GB" -f $_.Name, $total | Write-Host
    }
    return
}

New-Item -ItemType Directory -Force $dest | Out-Null
Write-Host "Destination: $((Resolve-Path $dest).Path)"
foreach ($f in $selected) {
    $target = Join-Path $dest $f.out
    if (Test-Path $target) { Write-Host "have $($f.out)"; continue }
    Write-Host "$($f.id): $($f.out) ($($f.gb) GB)"
    & curl.exe -L --fail -C - -o "$target.part" "https://huggingface.co/$($f.repo)/resolve/main/$($f.file)"
    if ($LASTEXITCODE -ne 0) { throw "download failed: $($f.repo)/$($f.file)" }
    Move-Item "$target.part" $target
}
Write-Host "Done."
