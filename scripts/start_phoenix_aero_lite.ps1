[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$ProjectRoot,
    [switch]$NoBrowser,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$SourceRoot = $ProjectRoot
$RuntimeRoot = $SourceRoot
$WorktreesDirectory = Split-Path -Parent $SourceRoot
if ((Split-Path -Leaf $WorktreesDirectory) -eq '.worktrees') {
    $SharedRoot = Split-Path -Parent $WorktreesDirectory
    if (Test-Path -LiteralPath (Join-Path $SharedRoot '.venv\Scripts\python.exe') -PathType Leaf) {
        $RuntimeRoot = $SharedRoot
    }
}
$Python = Join-Path $RuntimeRoot '.venv\Scripts\python.exe'
$ToolConfig = Join-Path $RuntimeRoot 'config\local_tools.json'
$LauncherData = Join-Path $RuntimeRoot 'web-data\launcher'
$Url = "http://127.0.0.1:$Port/"

function Stop-WithMessage([string]$Message, [int]$Code) {
    Write-Host "[无法启动] $Message" -ForegroundColor Red
    exit $Code
}

Write-Host 'Phoenix Aero Lite 启动检查' -ForegroundColor Cyan
Write-Host "程序源码：$SourceRoot"
Write-Host "本机运行数据：$RuntimeRoot"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Stop-WithMessage '未找到项目 Python 环境。请运行项目安装或修复程序。' 11
}
if (-not (Test-Path -LiteralPath $ToolConfig -PathType Leaf)) {
    Stop-WithMessage '缺少 config\local_tools.json，无法确认 SU2 官方程序位置。' 12
}
try {
    $Config = Get-Content -Raw -Encoding UTF8 -LiteralPath $ToolConfig | ConvertFrom-Json
    $Su2 = [string]$Config.su2_cfd_executable
} catch {
    Stop-WithMessage '本机工具配置无法读取，请检查 JSON 格式。' 13
}
if (-not $Su2 -or -not (Test-Path -LiteralPath $Su2 -PathType Leaf)) {
    Stop-WithMessage '配置中的 SU2_CFD.exe 不存在，不能启动真实求解。' 14
}
if ($Port -lt 1 -or $Port -gt 65535) {
    Stop-WithMessage '端口必须在 1 到 65535 之间。' 15
}
$Listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($Listener) {
    $Owners = ($Listener | Select-Object -ExpandProperty OwningProcess -Unique) -join '、'
    Stop-WithMessage "端口 $Port 已被进程 $Owners 占用。可双击后添加参数 -Port 8001。" 16
}

$env:PYTHONPATH = Join-Path $SourceRoot 'src'
& $Python -c "import fastapi, uvicorn, gmsh, meshio, pyvista; print('Gmsh ' + gmsh.__version__ + ' / PyVista ' + pyvista.__version__)"
if ($LASTEXITCODE -ne 0) {
    Stop-WithMessage 'Python、Gmsh、PyVista 或网页依赖不完整。' 17
}
Write-Host 'Python 与三维依赖检查通过。' -ForegroundColor Green
Write-Host "SU2：$Su2" -ForegroundColor Green
if ($CheckOnly) {
    Write-Host '检查完成：可以启动。' -ForegroundColor Green
    exit 0
}

New-Item -ItemType Directory -Force -Path $LauncherData | Out-Null
$Stdout = Join-Path $LauncherData 'backend_stdout.txt'
$Stderr = Join-Path $LauncherData 'backend_stderr.txt'
$Arguments = @(
    '-m', 'phoenix_aero_lite.web.server',
    '--host', '127.0.0.1',
    '--port', [string]$Port,
    '--project-root', $RuntimeRoot
)
$Backend = $null
try {
    $Backend = Start-Process -FilePath $Python -ArgumentList $Arguments -PassThru `
        -WindowStyle Hidden -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr
    Write-Host '正在启动本地后端…'
    $Ready = $false
    foreach ($Attempt in 1..60) {
        if ($Backend.HasExited) { break }
        try {
            $Health = Invoke-RestMethod -Uri ($Url + 'api/health') -TimeoutSec 1
            if ($Health.status -eq 'ok') { $Ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 250
    }
    if (-not $Ready) {
        $Detail = if (Test-Path -LiteralPath $Stderr) { Get-Content -Tail 8 -LiteralPath $Stderr } else { '无后端日志' }
        throw "后端未在规定时间内就绪。`n$($Detail -join "`n")"
    }
    Write-Host "启动成功：$Url" -ForegroundColor Green
    Write-Host '保持此窗口打开即可使用；关闭窗口会停止本地后端。'
    if (-not $NoBrowser) {
        Start-Process $Url
    }
    $Backend.WaitForExit()
    $Backend.Refresh()
    $BackendExitCode = $Backend.ExitCode
    if ($null -eq $BackendExitCode) { $BackendExitCode = -1 }
    if ($BackendExitCode -ne 0) {
        throw "WEB_BACKEND_RUNTIME_FAILED：后端异常退出，退出码 $BackendExitCode。请查看 $Stderr。"
    }
} catch {
    Write-Host "[启动失败] $($_.Exception.Message)" -ForegroundColor Red
    exit 18
} finally {
    if ($Backend -and -not $Backend.HasExited) {
        Stop-Process -Id $Backend.Id -Force -ErrorAction SilentlyContinue
        Write-Host '本地后端已清理。'
    }
}
