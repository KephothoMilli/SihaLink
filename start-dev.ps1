# Start both backend and frontend servers for development testing

Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     SihaLink Development Environment Startup                 ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Get the script directory
$scriptDir = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition
$venvPath = Join-Path $scriptDir "SihaLinkEnv"
$venvActivate = Join-Path $venvPath "Scripts\Activate.ps1"

# Check if virtual environment exists
if (-not (Test-Path $venvActivate)) {
    Write-Host "❌ Virtual environment not found at: $venvPath" -ForegroundColor Red
    Write-Host "Please run: python -m venv SihaLinkEnv" -ForegroundColor Yellow
    exit 1
}

# Activate virtual environment
Write-Host "🔧 Activating virtual environment..." -ForegroundColor Yellow
& $venvActivate
Write-Host "✅ Virtual environment activated" -ForegroundColor Green
Write-Host ""

# Check required environment variables
Write-Host "🔍 Checking environment variables..." -ForegroundColor Yellow
$requiredEnvVars = @("GEMINI_API_KEY", "MONGODB_ATLAS_URI")
$missingVars = @()

foreach ($var in $requiredEnvVars) {
    if ([string]::IsNullOrEmpty((Get-Item -Path "env:$var" -ErrorAction SilentlyContinue).Value)) {
        $missingVars += $var
    }
}

if ($missingVars.Count -gt 0) {
    Write-Host "⚠️  Missing environment variables: $($missingVars -join ', ')" -ForegroundColor Yellow
    Write-Host "Please set them or the application may not work correctly." -ForegroundColor Yellow
}
else {
    Write-Host "✅ All required environment variables are set" -ForegroundColor Green
}
Write-Host ""

# Start backend server
Write-Host "🚀 Starting Backend Server (FastAPI/Uvicorn)..." -ForegroundColor Yellow
Write-Host "   Command: uvicorn agents.orchestrator.agent:app --reload --port 8000" -ForegroundColor Gray

$backendProcess = Start-Process -FilePath "python" -ArgumentList "-m uvicorn agents.orchestrator.agent:app --reload --port 8000" `
    -WorkingDirectory $scriptDir -PassThru -NoNewWindow
$backendPID = $backendProcess.Id

Write-Host "✅ Backend Server started (PID: $backendPID)" -ForegroundColor Green
Write-Host "   📍 Available at: http://localhost:8000" -ForegroundColor Cyan
Write-Host "   📍 API Docs: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""

# Give backend a moment to start
Start-Sleep -Seconds 2

# Navigate to frontend directory
$frontendDir = Join-Path $scriptDir "frontend"
if (-not (Test-Path $frontendDir)) {
    Write-Host "❌ Frontend directory not found at: $frontendDir" -ForegroundColor Red
    Stop-Process -Id $backendPID -Force -ErrorAction SilentlyContinue
    exit 1
}

# Start frontend server
Write-Host "🚀 Starting Frontend Server (Angular)..." -ForegroundColor Yellow
Write-Host "   Command: npm start" -ForegroundColor Gray

$frontendProcess = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm start" `
    -WorkingDirectory $frontendDir -PassThru -NoNewWindow
$frontendPID = $frontendProcess.Id

Write-Host "✅ Frontend Server started (PID: $frontendPID)" -ForegroundColor Green
Write-Host "   📍 Available at: http://localhost:4200" -ForegroundColor Cyan
Write-Host ""

Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ ✅ Both servers are running!                                  ║" -ForegroundColor Cyan
Write-Host "╠════════════════════════════════════════════════════════════════╣" -ForegroundColor Cyan
Write-Host "║ Backend:   http://localhost:8000                               ║" -ForegroundColor Cyan
Write-Host "║ Frontend:  http://localhost:4200                               ║" -ForegroundColor Cyan
Write-Host "║                                                                ║" -ForegroundColor Cyan
Write-Host "║ Press Ctrl+C to stop the servers                               ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Wait for user to stop
try {
    $backendProcess.WaitForExit()
}
catch {
    # Handle Ctrl+C
}

# Cleanup
Write-Host ""
Write-Host "🛑 Shutting down servers..." -ForegroundColor Yellow
if ($null -ne $backendPID) {
    Stop-Process -Id $backendPID -Force -ErrorAction SilentlyContinue
}
if ($null -ne $frontendPID) {
    Stop-Process -Id $frontendPID -Force -ErrorAction SilentlyContinue
}
Write-Host "✅ Servers stopped" -ForegroundColor Green
