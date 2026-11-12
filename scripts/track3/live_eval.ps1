# Host-only real-model run. The agent does not execute this script.
param(
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$PythonExecutable = 'python',
    [switch]$ExclusiveGpuWindow
)
$ErrorActionPreference = 'Stop'
if (-not $ExclusiveGpuWindow) {
    throw 'Сначала согласуйте окно без параллельной нагрузки GPU. Затем передайте -ExclusiveGpuWindow.'
}
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $taskRoot
try {
    & $PythonExecutable scripts/track3/evaluate.py --dataset photoprint-v2 --exclusive-gpu-window --output $OutputPath
    $taskExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $taskExitCode
