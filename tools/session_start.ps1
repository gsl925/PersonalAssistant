# Idempotent stack launcher for the Claude Code SessionStart hook.
#
# Unlike start_all.bat (unconditional, meant for a manual double-click),
# this checks what's already running before launching anything, so opening
# a second Claude Code session in this project doesn't spawn duplicate
# processes or error out trying to rebind ports 6333/8000.

$root = Split-Path -Parent $PSScriptRoot

function Test-PortOpen($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $conn
}

$backendWasUp = Test-PortOpen 8000
$qdrantWasUp = Test-PortOpen 6333
$widgetWasUp = $null -ne (Get-Process electron -ErrorAction SilentlyContinue)

if (-not $qdrantWasUp) {
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList '/c', 'start', '"Qdrant"', 'cmd', '/k', "`"$root\tools\qdrant\start_qdrant.bat`"" `
        -WorkingDirectory $root
}

if (-not $backendWasUp) {
    # Same class of bug as the widget line below: a quoted path handed to
    # cmd.exe through PowerShell's -ArgumentList gets backslash-escaped by
    # .NET, which cmd.exe's own quote parser doesn't understand, and it
    # fails with "檔案名稱、目錄名稱或磁碟區標籤語法錯誤" instead of running
    # start.py. Routing through a plain .bat file sidesteps the quoting.
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList '/c', 'start', '"Personal AI Assistant"', 'cmd', '/k', "`"$root\tools\start_backend.bat`"" `
        -WorkingDirectory $root
}

# llama-swap (the local LLM server on :8090) is needed by dev_agent, KB Q&A,
# video digests, etc., so make sure it is answering. ensure_llama.ps1 does
# nothing if it already responds, and waits up to 120 s otherwise - far past
# this hook's 30 s timeout - so run it in a detached hidden process instead of
# blocking here. Skipped when the llama.cpp binaries were never downloaded.
if (Test-Path "$root\tools\llama\bin") {
    Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "$root\tools\llama\ensure_llama.ps1"
    )
}

if (-not $widgetWasUp) {
    # Launch electron.exe directly instead of routing through npm/cmd, so no
    # console window ever appears — the widget only shows up as a tray icon.
    # It must be quit from the tray menu ("結束"); there's no window to close.
    Start-Process -FilePath "$root\desktop\node_modules\electron\dist\electron.exe" `
        -ArgumentList '.' `
        -WorkingDirectory "$root\desktop" `
        -WindowStyle Hidden
}

# Only pop open a dashboard tab when THIS run is the one that started the
# backend — otherwise every session start would open a fresh tab even
# though the dashboard was already open from before.
if (-not $backendWasUp) {
    Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -ArgumentList @(
        "-NoProfile", "-Command",
        "for (`$i = 0; `$i -lt 60; `$i++) { if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { Start-Process 'http://localhost:8000/dashboard/'; break }; Start-Sleep -Seconds 1 }"
    )
}
