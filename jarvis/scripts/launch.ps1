$JARVIS_DIR = "$HOME\Downloads\SDP_Agentic_AI\jarvis"
if (Test-Path $JARVIS_DIR) { Set-Location $JARVIS_DIR }
elseif (-not (Test-Path ".\SDP Agentic AI.py")) { Write-Host "Cannot find jarvis. Edit JARVIS_DIR in launch.ps1" -ForegroundColor Red; exit 1 }
if (Test-Path ".\ai_env\Scripts\Activate.ps1") { .\ai_env\Scripts\Activate.ps1 }
else { Write-Host "Run setup.ps1 first." -ForegroundColor Red; exit 1 }
$ol = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ol) { Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep 3 }
python "SDP Agentic AI.py"
