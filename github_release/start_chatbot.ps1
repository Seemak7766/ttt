$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$pythonPath = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python virtual environment not found: .venv'
}

# Limit numerical worker threads to reduce memory usage during server startup.
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'

try {
    $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 2
    if ($health.StatusCode -eq 200) {
        Write-Output 'Chatbot is already running: http://127.0.0.1:8501/'
        exit 0
    }
} catch {}

$serverProcess = Start-Process -FilePath $pythonPath -ArgumentList @(
    '-m', 'streamlit', 'run', 'app.py',
    '--server.headless', 'true', '--server.address', '127.0.0.1',
    '--server.port', '8501', '--browser.gatherUsageStats', 'false'
) -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput (Join-Path $taskRoot 'streamlit.stdout.log') `
  -RedirectStandardError (Join-Path $taskRoot 'streamlit.stderr.log')

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Seconds 1
    $serverProcess.Refresh()
    if ($serverProcess.HasExited) {
        throw 'Chatbot startup failed. See streamlit.stderr.log in the project folder.'
    }
    try {
        $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 2
        if ($health.StatusCode -eq 200) {
            Write-Output "Chatbot ready: http://127.0.0.1:8501/ (PID $($serverProcess.Id))"
            exit 0
        }
    } catch {}
}
throw 'Chatbot did not respond within the startup timeout.'
