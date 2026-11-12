$ErrorActionPreference = 'Stop'
$archiveProjectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$archiveParent = [IO.Directory]::GetParent($archiveProjectRoot).FullName
$archiveTarget = Join-Path $archiveParent ("focus-source-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.zip')
if (Test-Path -LiteralPath $archiveTarget) { throw 'Archive already exists.' }
# Archive committed sources only; ignored files and local secrets are never read.
& git -C $archiveProjectRoot archive --format=zip --prefix=focus/ --output=$archiveTarget HEAD
if ($LASTEXITCODE -ne 0) { throw 'Source archive failed.' }
[PSCustomObject]@{
    Path = $archiveTarget
    Bytes = (Get-Item -LiteralPath $archiveTarget).Length
    SHA256 = (Get-FileHash -LiteralPath $archiveTarget -Algorithm SHA256).Hash
}
