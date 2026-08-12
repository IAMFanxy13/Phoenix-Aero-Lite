[CmdletBinding()]
param(
    [string]$Python = ".venv\Scripts\python.exe",
    [string]$Su2Executable = "",
    [string]$ProtectedStep = "",
    [string]$ProtectedSolidWorks = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = if ([IO.Path]::IsPathRooted($Python)) {
    $Python
} else {
    Join-Path $ProjectRoot $Python
}
$Evidence = Join-Path $ProjectRoot "artifacts\release_verification"
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null

if ([bool]$ProtectedStep -xor [bool]$ProtectedSolidWorks) {
    throw "ProtectedStep and ProtectedSolidWorks must be supplied together."
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python was not found: $PythonPath"
}
if ($Su2Executable) {
    $env:PAL_SU2_CFD = (Resolve-Path -LiteralPath $Su2Executable).Path
}
$env:PYTHONPATH = Join-Path $ProjectRoot "src"

Push-Location $ProjectRoot
try {
    & $PythonPath -m pytest -q *> (Join-Path $Evidence "pytest.txt")
    $PytestExit = $LASTEXITCODE
    & $PythonPath -m compileall -q src *> (Join-Path $Evidence "compileall.txt")
    $CompileExit = $LASTEXITCODE
    & $PythonPath scripts\audit_licenses.py *> (Join-Path $Evidence "license_audit.json")
    $LicenseExit = $LASTEXITCODE
    & $PythonPath scripts\verify_runtime.py $ProjectRoot *> (Join-Path $Evidence "runtime.json")
    $RuntimeExit = $LASTEXITCODE
    $PrivateSourceEvidence = [ordered]@{
        status = "PRIVATE_SOURCE_CHECK_NOT_REQUESTED"
        files = @()
    }
    if ($ProtectedStep -and $ProtectedSolidWorks) {
        $ProtectedPaths = @(
            (Resolve-Path -LiteralPath $ProtectedStep).Path
            (Resolve-Path -LiteralPath $ProtectedSolidWorks).Path
        )
        $PrivateSourceEvidence.status = "PRIVATE_SOURCE_HASHES_RECORDED"
        $PrivateSourceEvidence.files = @(
            Get-FileHash $ProtectedPaths -Algorithm SHA256 |
                Select-Object Path, Hash
        )
    }
    $PrivateSourceEvidence |
        ConvertTo-Json -Depth 4 |
        Set-Content -Encoding utf8 (Join-Path $Evidence "source_hashes.json")
    git rev-parse HEAD | Set-Content -Encoding ascii (Join-Path $Evidence "git_head.txt")
    $Summary = [ordered]@{
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        pytest_exit_code = $PytestExit
        compileall_exit_code = $CompileExit
        license_audit_exit_code = $LicenseExit
        runtime_exit_code = $RuntimeExit
        private_source_check = $PrivateSourceEvidence.status
        fluent_comparison = "NOT_RUN_NO_APPROVED_BASELINE"
        engineering_result_status = "NOT_VALIDATED_PREVIEW_SMOKE_ONLY"
    }
    $Summary | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Evidence "summary.json")
    if (($PytestExit + $CompileExit + $LicenseExit + $RuntimeExit) -ne 0) {
        throw "One or more release gates failed. See $Evidence"
    }
} finally {
    Pop-Location
}
Write-Host "Release verification passed: $Evidence"
