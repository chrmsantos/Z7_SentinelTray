$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$logDir = Join-Path $root "config\logs\scripts"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "build_exe_$timestamp.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Get-ChildItem -Path (Join-Path $logDir "build_exe_*.log") -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 5 |
    Remove-Item -Force -ErrorAction SilentlyContinue

function Write-Log {
    param(
        [string]$Level,
        [string]$Message
    )
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level.ToUpper(), $Message
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

Write-Log "INFO" "Build named executable started"
Write-Log "INFO" "Root: $root"

$pythonCandidates = @(
    (Join-Path $root ".venv\Scripts\python.exe"),
    (Join-Path $root "runtime\python\python.exe")
)
$python = $null
foreach ($candidate in $pythonCandidates) {
    if (Test-Path $candidate) {
        $python = $candidate
        break
    }
}
if (-not $python) {
    $python = "python"
}
Write-Log "INFO" "Python: $python"

try {
    & $python -m pip install --upgrade pip pyinstaller | ForEach-Object { Write-Log "INFO" $_ }
} catch {
    Write-Log "ERROR" "Failed to install PyInstaller. Ensure pip is available and try again."
    throw
}

$distPath = Join-Path $root "dist"
$workPath = Join-Path $root "build\pyinstaller"

$specFile = Join-Path $root "Z7_SentinelTray.spec"

try {
    & $python -m PyInstaller --noconfirm --clean `
        --distpath $distPath --workpath $workPath $specFile | ForEach-Object { Write-Log "INFO" $_ }
} catch {
    Write-Log "ERROR" "PyInstaller build failed."
    throw
}

$exePath = Join-Path $distPath "Z7_SentinelTray.exe"
if (Test-Path $exePath) {
    Write-Log "INFO" "Build complete: $exePath"
    Write-Log "INFO" "Task Manager will show: Z7_SentinelTray.exe"
} else {
    Write-Log "ERROR" "Executable not found after build: $exePath"
    throw "Build failed"
}
