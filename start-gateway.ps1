# Открывает твою локальную Ollama для коллег через шлюз с ключом.
#   .\start-gateway.ps1                   # Tailscale (рекомендуется): частная сеть, постоянный адрес
#   .\start-gateway.ps1 -Mode cloudflare  # публичный HTTPS-туннель, у коллег ничего не ставится
#   .\start-gateway.ps1 -Mode lan         # только одна локальная сеть / офис
#   .\start-gateway.ps1 -NewKey           # выпустить новый ключ (старый перестанет работать)
param(
    [ValidateSet('tailscale','cloudflare','lan')][string]$Mode = 'tailscale',
    [int]$Port = 11500,
    [switch]$NewKey
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$py = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $py)) { throw 'Сначала создайте .venv и установите requirements-local.txt.' }
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'data') -Force | Out-Null

# --- Ollama: только на loopback, наружу смотрит лишь шлюз ---
$ollamaCmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
$ollama = if ($ollamaCmd) { $ollamaCmd.Source } else { Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe' }
if (-not (Test-Path -LiteralPath $ollama)) { throw 'Не найден Ollama.' }
$env:OLLAMA_HOST = '127.0.0.1:11434'
if (-not $env:OLLAMA_MODELS) { $env:OLLAMA_MODELS = Join-Path $env:USERPROFILE '.ollama/models' }
$env:OLLAMA_NO_CLOUD = '1'
# Несколько коллег: держим одну модель в памяти, запросы встают в очередь.
$env:OLLAMA_MAX_LOADED_MODELS = '1'
if (-not $env:OLLAMA_NUM_PARALLEL) { $env:OLLAMA_NUM_PARALLEL = '2' }
$ollamaProc = $null; $tunnelProc = $null
function Test-Ollama { try { $null = Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2; $true } catch { $false } }

if ($NewKey) { Remove-Item -LiteralPath (Join-Path $PSScriptRoot 'secrets/llm_gateway.token') -ErrorAction SilentlyContinue }
$token = (& $py scripts/llm_gateway.py --show-token | Select-Object -Last 1).Trim()

try {
    if (-not (Test-Ollama)) {
        $ollamaProc = Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput 'data/ollama.stdout.log' -RedirectStandardError 'data/ollama.stderr.log'
        for ($i = 0; $i -lt 30 -and -not (Test-Ollama); $i++) { Start-Sleep -Seconds 1 }
        if (-not (Test-Ollama)) { throw 'Ollama не запустился. Проверьте data/ollama.stderr.log.' }
    }

    switch ($Mode) {
        'tailscale' {
            $ts = Get-Command tailscale.exe -ErrorAction SilentlyContinue
            $tsPath = if ($ts) { $ts.Source } else { 'C:/Program Files/Tailscale/tailscale.exe' }
            if (-not (Test-Path -LiteralPath $tsPath)) { throw 'Tailscale не установлен: https://tailscale.com/download (или запустите с -Mode cloudflare).' }
            $bindHost = (& $tsPath ip -4 | Select-Object -First 1).Trim()
            if (-not $bindHost) { throw 'Tailscale не подключён. Откройте Tailscale и войдите в аккаунт.' }
            $publicUrl = "http://${bindHost}:$Port"
        }
        'lan' {
            $bindHost = '0.0.0.0'
            $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -in 'Dhcp','Manual' -and $_.IPAddress -notlike '169.*' } | Select-Object -First 1).IPAddress
            $publicUrl = "http://${ip}:$Port"
            Write-Warning 'LAN-режим: трафик внутри сети не шифруется. Ключ виден любому, кто перехватывает трафик в этой сети.'
        }
        'cloudflare' {
            $bindHost = '127.0.0.1'
            $cf = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
            if (-not $cf) { throw 'Нет cloudflared: winget install --id Cloudflare.cloudflared' }
            $cfLog = Join-Path $PSScriptRoot 'data/cloudflared.log'
            Remove-Item -LiteralPath $cfLog -ErrorAction SilentlyContinue
            $tunnelProc = Start-Process -FilePath $cf.Source -ArgumentList 'tunnel','--no-autoupdate','--url',"http://127.0.0.1:$Port" `
                -WindowStyle Hidden -PassThru -RedirectStandardError $cfLog -RedirectStandardOutput 'data/cloudflared.stdout.log'
            $publicUrl = $null
            for ($i = 0; $i -lt 40 -and -not $publicUrl; $i++) {
                Start-Sleep -Seconds 1
                if (Test-Path -LiteralPath $cfLog) {
                    $m = Select-String -LiteralPath $cfLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
                    if ($m) { $publicUrl = $m.Matches[0].Value }
                }
            }
            if (-not $publicUrl) { throw 'cloudflared не выдал адрес. Смотрите data/cloudflared.log.' }
        }
    }

    $model = (Select-String -LiteralPath '.env' -Pattern '^OLLAMA_MODEL=(.+)$' -ErrorAction SilentlyContinue | Select-Object -First 1).Matches.Groups[1].Value
    if (-not $model) { $model = 'qwen3:4b-instruct' }
    Write-Host ''
    Write-Host '=== Отправьте коллегам ЛИЧНО (не в GitHub) — строки для их .env ===' -ForegroundColor Cyan
    Write-Host "OLLAMA_BASE_URL=$publicUrl"
    Write-Host "OLLAMA_API_KEY=$token"
    Write-Host "OLLAMA_MODEL=$model"
    Write-Host '======================================================================' -ForegroundColor Cyan
    if ($Mode -eq 'cloudflare') { Write-Host 'Адрес trycloudflare меняется при каждом перезапуске — его придётся пересылать заново.' -ForegroundColor Yellow }
    Write-Host 'Компьютер должен быть включён, окно не закрывайте. Ctrl+C — остановить.'
    Write-Host ''
    & $py scripts/llm_gateway.py --host $bindHost --port $Port
} finally {
    if ($tunnelProc -and -not $tunnelProc.HasExited) { Stop-Process -Id $tunnelProc.Id }
    if ($ollamaProc -and -not $ollamaProc.HasExited) { Stop-Process -Id $ollamaProc.Id }
}
