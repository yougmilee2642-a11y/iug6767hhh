$ErrorActionPreference = "Stop"
$archiveProjectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$archiveParent = [IO.Directory]::GetParent($archiveProjectRoot).FullName
$archiveTarget = Join-Path $archiveParent ("Callwise-local-source-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".zip")
if (Test-Path -LiteralPath $archiveTarget) { throw "Archive already exists." }
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archiveStream = [IO.File]::Open($archiveTarget, [IO.FileMode]::CreateNew)
$archiveZip = [IO.Compression.ZipArchive]::new($archiveStream, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($archiveFile in Get-ChildItem -LiteralPath $archiveProjectRoot -Recurse -File -Force) {
        $archiveRelative = [IO.Path]::GetRelativePath($archiveProjectRoot, $archiveFile.FullName).Replace('\', '/')
        if (("/" + $archiveRelative) -match '/(?:data|models|downloads|proof|\.venv|venv|__pycache__|\.pytest_cache|\.git|node_modules|work|outputs|secrets|\.openai|__MACOSX)/') { continue }
        if ($archiveRelative -eq 'configs/integrations.local.json') { continue }
        if ($archiveFile.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        if ($archiveFile.Name -eq '.DS_Store' -or $archiveFile.Name -like '._*') { continue }
        if ($archiveFile.Name -like ".env*" -and $archiveFile.Name -notin @('.env.example','.env.local.example')) { continue }
        if ($archiveFile.Extension -match '^\.(?:pyc|zip|sqlite|sqlite3|db|log|key|pem|pfx|whl)$') { continue }
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archiveZip, $archiveFile.FullName, "Callwise/" + $archiveRelative, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally {
    $archiveZip.Dispose()
    $archiveStream.Dispose()
}
$archiveRead = [IO.Compression.ZipFile]::OpenRead($archiveTarget)
try {
    $archiveNames = @($archiveRead.Entries.FullName)
    foreach ($archiveLocalRequired in @('.env.local.example','requirements-local.txt','start-local.ps1','LOCAL_SETUP.md','TEAM_DEVELOPMENT.md','providers/ollama.py','services/local_speech.py','scripts/smoke-local.py')) {
        if ('Callwise/' + $archiveLocalRequired -notin $archiveNames) { throw "Missing local entry: $archiveLocalRequired" }
    }
    foreach ($archiveRequired in @("app.py", ".env.example", "requirements.txt", "README.md", "ITERATION_3_2_REPORT.md", "requirement_contract.py", "evaluation/plan.py", "evaluation/service.py", "evaluation/knowledge.py", "evaluation/preflight.py", "evaluation/provider_diagnostics.py", "providers/errors.py", "providers/capabilities.py", "static/evaluation.js", "tests/test_iteration_3_2.py")) {
        if ("Callwise/" + $archiveRequired -notin $archiveNames) { throw "Missing entry: $archiveRequired" }
    }
    if ('Callwise/configs/integrations.local.json' -in $archiveNames) { throw 'Private integration settings present.' }
    if ($archiveNames | Where-Object { $_ -match '/(?:data|models|downloads|proof|\.venv|__pycache__|\.pytest_cache|work|outputs|secrets|\.openai|__MACOSX)/|/(?:\.DS_Store|\._[^/]+)$|/\.env(?:$|\.(?!(?:local\.)?example$))' }) { throw "Excluded files present." }
    [PSCustomObject]@{Path=$archiveTarget; Entries=$archiveNames.Count; Bytes=(Get-Item -LiteralPath $archiveTarget).Length; SHA256=(Get-FileHash -LiteralPath $archiveTarget -Algorithm SHA256).Hash}
} finally { $archiveRead.Dispose() }
