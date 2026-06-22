$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host "[deploy] Building executable..."
& (Join-Path $PSScriptRoot "build_named_exe.ps1")

$exe = Join-Path $root "dist\Z7_SentinelTray.exe"
if (-not (Test-Path $exe)) {
    Write-Error "[deploy] Build succeeded but dist\Z7_SentinelTray.exe was not found."
    exit 1
}

$info = Get-Item $exe
Write-Host ""
Write-Host "[deploy] Ready: $($info.FullName)"
Write-Host "[deploy] Size : $([math]::Round($info.Length / 1MB, 2)) MB"
Write-Host "[deploy] Date : $($info.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
