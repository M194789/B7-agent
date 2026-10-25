$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $basePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (-not (Test-Path -LiteralPath $basePython)) { $basePython = (Get-Command python -ErrorAction Stop).Source }
    & $basePython -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment.' }
    & $python -m pip install -r (Join-Path $PSScriptRoot 'requirements.lock.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
$listenPort = 8017
if ($env:B7_PORT) { $listenPort = [int]$env:B7_PORT }
try {
    $existing = Invoke-RestMethod -Uri "http://127.0.0.1:$listenPort/api/health" -TimeoutSec 2
    if ($existing.version -eq '0.2.0' -and $existing.status -eq 'ok') {
        Write-Host "Demo is already running: http://127.0.0.1:$listenPort"
        exit 0
    }
} catch {}
if (Get-NetTCPConnection -State Listen -LocalPort $listenPort -ErrorAction SilentlyContinue) {
    throw "Port $listenPort is occupied by another application. Set B7_PORT to use a different port."
}
$logDir = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$process = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$listenPort") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'stdout.log') -RedirectStandardError (Join-Path $logDir 'stderr.log')
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'demo.pid'), [string]$process.Id)
for ($attempt=0; $attempt -lt 30; $attempt++) {
    if ($process.HasExited) { throw 'Demo stopped during startup. Inspect logs/stderr.log.' }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$listenPort/api/health" -TimeoutSec 2
        if ($health.status -eq 'ok') { Write-Host "Demo is ready: http://127.0.0.1:$listenPort"; exit 0 }
    } catch {}
    Start-Sleep -Milliseconds 700
}
throw 'Startup did not complete in time. Inspect logs/stderr.log.'
