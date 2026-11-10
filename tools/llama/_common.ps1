# Shared by download_models.ps1 and link_ollama_models.ps1 (dot-sourced).

# Where the GGUF files live. First match wins:
#   explicit -Dest  >  LLM_MODELS_DIR environment variable  >  LLM_MODELS_DIR in the repo's .env
#   >  data\llm_models inside the repo (gitignored).
function Get-ModelsDir([string]$Explicit) {
    if ($Explicit) { return $Explicit }
    if ($env:LLM_MODELS_DIR) { return $env:LLM_MODELS_DIR }
    $envFile = Join-Path $PSScriptRoot "..\..\.env"
    if (Test-Path $envFile) {
        foreach ($line in Get-Content $envFile) {
            if ($line -match '^\s*LLM_MODELS_DIR\s*=\s*(.*?)\s*$' -and $Matches[1].Trim('"', "'")) {
                return $Matches[1].Trim('"', "'")
            }
        }
    }
    return Join-Path $PSScriptRoot "..\..\data\llm_models"
}
