Write-Host "LOCAL AGENTIC AI - SDP Setup" -ForegroundColor Cyan
Write-Host "[1/5] Python..." -ForegroundColor Yellow
python --version 2>&1
if ($LASTEXITCODE -ne 0) { Write-Host "Install Python from python.org" -ForegroundColor Red; exit 1 }
Write-Host "[2/5] Ollama..." -ForegroundColor Yellow
ollama --version 2>&1
if ($LASTEXITCODE -ne 0) { Write-Host "Install Ollama from ollama.com" -ForegroundColor Red; exit 1 }
Write-Host "[3/5] llama3 model..." -ForegroundColor Yellow
if (-not (ollama list 2>&1 | Select-String "llama3")) { ollama pull llama3 }
else { Write-Host "  llama3 ready" -ForegroundColor Green }
Write-Host "[4/5] Virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path ".\ai_env")) { python -m venv ai_env }
.\ai_env\Scripts\Activate.ps1
Write-Host "[5/5] Installing packages..." -ForegroundColor Yellow
foreach ($p in @("requests","langchain-ollama","langchain-community","pandas","matplotlib","numpy","playwright","rich")) {
    pip install $p -q --disable-pip-version-check
    Write-Host "  $p OK" -ForegroundColor DarkGray
}
playwright install chromium --quiet 2>&1 | Out-Null
foreach ($d in @("memory","generated_code","logs","logs/monitor","data","data/cache")) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}
$ol = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ol) { Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep 3 }
Write-Host ""
Write-Host "AGENT ready! Run: .\scripts\launch.ps1" -ForegroundColor Green
