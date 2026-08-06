$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
$pip = Join-Path $venv 'Scripts\pip.exe'
$web = Join-Path $root 'apps\web'

function Invoke-Step($message, $scriptblock) {
  Write-Host $message
  & $scriptblock
  if ($LASTEXITCODE -ne 0) {
    throw "Setup failed: $message (exit code $LASTEXITCODE)"
  }
}

if (Test-Path -LiteralPath $venv) {
  Write-Host 'Virtual environment already exists, skipping creation...'
} else {
  Invoke-Step 'Creating virtual environment...' { py -3.12 -m venv $venv }
}

Invoke-Step 'Installing Python dependencies...' { & $pip install -r (Join-Path $root 'requirements.txt') }
Invoke-Step 'Installing root npm dependencies...' { Push-Location $root; npm install; Pop-Location }
Invoke-Step 'Installing web npm dependencies...' { Push-Location $web; npm install; Pop-Location }
Invoke-Step 'Installing skills...' { & $python (Join-Path $root 'scripts\install_skills.py') --employee ALL }
Invoke-Step 'Verifying skills...' { & $python (Join-Path $root 'scripts\verify_skills.py') --employee ALL }
Invoke-Step 'Rendering skill indexes...' { & $python (Join-Path $root 'scripts\render_skill_indexes.py') }

Write-Host 'Setup complete.'
