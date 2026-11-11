$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$localPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $localPython)) { throw 'Сначала создайте .venv и установите requirements-local.txt.' }
$localOllamaCommand = Get-Command ollama.exe -ErrorAction SilentlyContinue
$localOllamaBinary = if ($localOllamaCommand) { $localOllamaCommand.Source } else { Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe' }
if (-not (Test-Path -LiteralPath $localOllamaBinary)) { throw 'Не найден Ollama. Установите официальный Ollama для Windows.' }
$env:OLLAMA_HOST = '127.0.0.1:11434'
# Use Ollama's normal store, the same one used by `ollama pull` and the desktop app.
# Respect a custom store, except the deprecated project store left by old launches.
$callwiseLegacyOllamaStore = Join-Path $PSScriptRoot 'models/ollama'
if (-not $env:OLLAMA_MODELS -or [IO.Path]::GetFullPath($env:OLLAMA_MODELS).TrimEnd('\', '/') -eq [IO.Path]::GetFullPath($callwiseLegacyOllamaStore).TrimEnd('\', '/')) {
    $env:OLLAMA_MODELS = Join-Path $env:USERPROFILE '.ollama/models'
}
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:CALLWISE_LOCAL_ONLY = 'true'
$env:AI_PROVIDER = 'ollama'
$env:PYTHONUTF8 = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$localOllamaProcess = $null
try {
    $localApiReady = $false
    try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 3; $localApiReady = $true } catch {}
    if (-not $localApiReady) {
        New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'data') -Force | Out-Null
        $localOllamaProcess = Start-Process -FilePath $localOllamaBinary -ArgumentList 'serve' -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot 'data/ollama.stdout.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data/ollama.stderr.log')
        for ($localAttempt=0; $localAttempt -lt 30; $localAttempt++) {
            try { $null=Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2; $localApiReady=$true; break } catch { Start-Sleep -Seconds 1 }
        }
    }
    if (-not $localApiReady) { throw 'Ollama не запустился. Проверьте data/ollama.stderr.log.' }
    Write-Host 'Callwise: http://127.0.0.1:8000 — локальная речь и текст, без внешних интеграций.'
    & $localPython -m uvicorn app:app --host 127.0.0.1 --port 8000
} finally {
    if ($localOllamaProcess -and -not $localOllamaProcess.HasExited) { Stop-Process -Id $localOllamaProcess.Id }
}
