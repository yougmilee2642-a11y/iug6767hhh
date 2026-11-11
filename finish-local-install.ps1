$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$finishPython=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$finishOllama=Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe'
$env:PYTHONUTF8='1'
$env:OLLAMA_HOST='127.0.0.1:11434'
$env:OLLAMA_MODELS=Join-Path $PSScriptRoot 'models/ollama'
$env:OLLAMA_NO_CLOUD='1'
& $finishPython scripts/download-qwen.py
if ($LASTEXITCODE -ne 0) { throw 'Загрузка Qwen не завершена; её можно возобновить тем же скриптом.' }
& $finishOllama create 'callwise-qwen3:4b-q4_K_M' -f Modelfile.local
if ($LASTEXITCODE -ne 0) { throw 'Не удалось импортировать проверенный GGUF в Ollama.' }
$env:OLLAMA_MODEL='callwise-qwen3:4b-q4_K_M'
& $finishPython scripts/smoke-local.py
if ($LASTEXITCODE -ne 0) { throw 'Модели установлены, но сквозная проверка не прошла. Не объявляйте прототип готовым.' }
& $finishOllama ps
Write-Host 'Локальная установка и smoke прошли. Для веб-интерфейса запустите start-local.ps1.'
