$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Python environment not found. Run: python -m venv .venv' }

# Ports are exclusively owned by this local development service.
# Legacy launchers left unrecoverable listeners on 8000/5173. The current
# supervisor owns only 8011/5175, so it always starts one clean API pair.
# On Windows, stopping only uvicorn's listener child leaves the --reload parent
# alive; it immediately respawns the stale build. Stop this root's full API
# process family before releasing ports.
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
  Where-Object {
    $_.CommandLine -like "*$root*uvicorn*apps.api.main:app*" -and
    $_.CommandLine -like "*--port*8011*"
  } |
  ForEach-Object {
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $($_.ProcessId)" -ErrorAction SilentlyContinue |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
foreach ($port in @(8011, 5175)) {
  Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
}

# Worker has no listening port. Stop only worker processes launched from this AI Office root.
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*$root*apps.api.worker*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$web = Join-Path $root 'apps\web'
Start-Process -FilePath $python -ArgumentList '-m','uvicorn','apps.api.main:app','--host','127.0.0.1','--port','8011','--reload' -WorkingDirectory $root -WindowStyle Hidden
Start-Process -FilePath $python -ArgumentList '-m','apps.api.worker' -WorkingDirectory $root -WindowStyle Hidden
Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev','--','--host','127.0.0.1','--port','5175' -WorkingDirectory $web -WindowStyle Hidden

$deadline = (Get-Date).AddSeconds(20)
do {
  try {
    $runtime = Invoke-RestMethod -Uri 'http://127.0.0.1:8011/api/runtime/version' -TimeoutSec 2
    if ($runtime.api_build_id -eq $runtime.worker_build_id) { Start-Process 'http://127.0.0.1:5175'; exit 0 }
  } catch {}
  Start-Sleep -Milliseconds 400
} while ((Get-Date) -lt $deadline)
throw 'AI Office API/worker failed readiness check. Browser was not opened.'
