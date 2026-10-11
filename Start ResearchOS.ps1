$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3.11 or newer is required. Install Python and enable 'Add Python to PATH'." }
$pythonArgs = @()
if ($python.Name -eq "py.exe" -or $python.Name -eq "py") { $pythonArgs = @("-3") }
$version = & $python.Source @pythonArgs -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$isOld = & $python.Source @pythonArgs -c "import sys; print(int(sys.version_info < (3, 11)))"
if ($isOld.Trim() -eq "1") { throw "ResearchOS needs Python 3.11 or newer. Found Python $version." }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "First run: creating the local Python environment..."
  & $python.Source @pythonArgs -m venv .venv
  if ($LASTEXITCODE -ne 0) { throw "Could not create the local Python environment." }
}
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
Write-Host "Preparing ResearchOS dependencies..."
& ".venv\Scripts\python.exe" -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw "Dependency setup failed. Check your internet connection and try again." }

$existing = $null
try { $existing = Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 1 } catch {}
if ($existing.service -eq "researchos") {
  Write-Host "ResearchOS is already running at http://127.0.0.1:8000. Opening the existing app."
  if ($env:RESEARCHOS_SKIP_BROWSER -ne "1") { Start-Process "http://127.0.0.1:8000" }
  exit 0
}

$ollamaReady = $false
try { Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null; $ollamaReady = $true } catch {}
if (-not $ollamaReady) {
  $ollama = Get-Command ollama -ErrorAction SilentlyContinue
  if ($ollama) {
    Write-Host "Starting the Ollama service..."
    Start-Process -FilePath $ollama.Source -ArgumentList "serve" -WindowStyle Hidden | Out-Null
  } else {
    Write-Host "Ollama was not found. The app will run, but local model analysis needs a connected model server."
  }
}

Write-Host "Starting ResearchOS at http://127.0.0.1:8000"
$server = Start-Process -FilePath ".venv\Scripts\researchos.exe" -ArgumentList @("serve", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $PSScriptRoot -PassThru -NoNewWindow
try {
  $ready = $false
  for ($attempt = 0; $attempt -lt 90; $attempt++) {
    if ($server.HasExited) { throw "ResearchOS stopped during startup. Port 8000 may be in use by another application." }
    try {
      $health = Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 1
      if ($health.service -eq "researchos") { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
  }
  if ($ready) {
    Write-Host "ResearchOS is ready. Press Control-C to stop it."
    if ($env:RESEARCHOS_SKIP_BROWSER -ne "1") { Start-Process "http://127.0.0.1:8000" }
  } else {
    Write-Host "The app is taking longer to start. Keep this window open and visit http://127.0.0.1:8000 when ready."
  }
  $server.WaitForExit()
} finally {
  if (-not $server.HasExited) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
}
