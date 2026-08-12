[CmdletBinding()]
param(
    [string]$Python = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ($env:OS -ne "Windows_NT") {
    throw "Phoenix Aero Lite can only be frozen on Windows."
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "THIRD_PARTY_NOTICES.md"))) {
    throw "THIRD_PARTY_NOTICES.md is required before packaging."
}
$PythonPath = if ([IO.Path]::IsPathRooted($Python)) {
    $Python
} else {
    Join-Path $ProjectRoot $Python
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python was not found: $PythonPath"
}
& $PythonPath -m PyInstaller --version
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed in the selected environment."
}
Push-Location $ProjectRoot
try {
    & $PythonPath -m PyInstaller --noconfirm --clean "packaging\phoenix_aero_lite.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
Write-Host "Build complete: $ProjectRoot\dist\PhoenixAeroLite\PhoenixAeroLite.exe"
