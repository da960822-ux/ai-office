$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Python environment not found. Run: python -m venv .venv' }

# Stop only processes launched from this AI Office root. On this Windows host,
# a forcibly stopped uvicorn --reload child can leave a stale kernel listener.
# The next launch therefore selects a new free port instead of trusting the old
# port to be reusable.
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object {
    $_.CommandLine -like "*$root*" -and (
      $_.CommandLine -like "*uvicorn*apps.api.main:app*" -or
      $_.CommandLine -like "*apps.api.worker*" -or
      $_.CommandLine -like "*vite*"
    )
  } |
  Sort-Object ParentProcessId -Descending |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Sleep -Milliseconds 300
$occupied = @(
  Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty LocalPort -Unique
)
$apiPort = 8100..8199 | Where-Object { $_ -notin $occupied } | Select-Object -First 1
$uiPort = 5175..5199 | Where-Object { $_ -notin $occupied } | Select-Object -First 1
if (-not $apiPort -or -not $uiPort) { throw 'No free local API/UI port is available.' }

$apiUrl = "http://127.0.0.1:$apiPort"
$uiUrl = "http://127.0.0.1:$uiPort"
$env:AI_OFFICE_API_URL = $apiUrl
$web = Join-Path $root 'apps\web'

Start-Process -FilePath $python -ArgumentList '-m','uvicorn','apps.api.main:app','--host','127.0.0.1','--port',"$apiPort",'--reload' -WorkingDirectory $root -WindowStyle Hidden
Start-Process -FilePath $python -ArgumentList '-m','apps.api.worker' -WorkingDirectory $root -WindowStyle Hidden
Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev','--','--host','127.0.0.1','--port',"$uiPort",'--strictPort' -WorkingDirectory $web -WindowStyle Hidden

$deadline = (Get-Date).AddSeconds(20)
do {
  try {
    $runtime = Invoke-RestMethod -Uri "$apiUrl/api/runtime/version" -TimeoutSec 2
    $webReady = (Invoke-WebRequest -Uri $uiUrl -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200
    if ($runtime.api_build_id -eq $runtime.worker_build_id -and $webReady) {
      $stateDir = Join-Path $root '.ai-office'
      New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
      @{
        api_url = $apiUrl
        ui_url = $uiUrl
        api_build_id = $runtime.api_build_id
        worker_build_id = $runtime.worker_build_id
        schema_version = $runtime.schema_version
        started_at = (Get-Date).ToString('o')
      } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stateDir 'runtime.json') -Encoding UTF8
      Start-Process $uiUrl
      exit 0
    }
  } catch {}
  Start-Sleep -Milliseconds 400
} while ((Get-Date) -lt $deadline)

throw "AI Office readiness check failed. API: $apiUrl, UI: $uiUrl"
