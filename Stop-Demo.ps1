$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'demo.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host 'No recorded Demo process.'; exit 0 }
$recordedId = [int](Get-Content -LiteralPath $pidFile -Raw)
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$recordedId" -ErrorAction SilentlyContinue
if (-not $process) { Write-Host 'Demo is already stopped.'; exit 0 }
$expected = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($process.ExecutablePath -ne $expected -or -not $process.CommandLine.Contains('app.main:app')) {
    throw 'Recorded process does not match this Demo. Nothing was stopped.'
}
Stop-Process -Id $recordedId
Write-Host 'Demo stopped. Tasks and graph checkpoints remain in data/.'
