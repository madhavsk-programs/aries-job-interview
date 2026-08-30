$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BackendPython = Join-Path $ProjectRoot "backend\.venv\Scripts\python.exe"
$Docker = Get-Command docker -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue
if (-not $Docker) {
    $DockerCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"),
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
    )
    $Docker = $DockerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

$Ollama = Get-Command ollama -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue
if (-not $Ollama) {
    $KnownOllama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path -LiteralPath $KnownOllama) {
        $Ollama = $KnownOllama
    }
}

if (-not $Docker) {
    throw "Docker Desktop was not found. Install or start Docker Desktop, then run this script again."
}

if (-not $Ollama) {
    throw "Ollama is not installed. Install the free Windows app from https://ollama.com/download/windows, then run this script again."
}

function Wait-ForUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$Attempts = 90
    )

    for ($Attempt = 1; $Attempt -le $Attempts; $Attempt++) {
        try {
            Invoke-RestMethod -Uri $Url -TimeoutSec 3 | Out-Null
            return
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "Timed out waiting for $Url"
}

function Ensure-SpeechModel {
    param([Parameter(Mandatory = $true)][string]$Model)

    # Speaches can list a model while a large file is still only partially cached.
    # Calling the download endpoint every time is safe: it validates completed
    # files, resumes interrupted downloads, and returns quickly for cached models.
    Write-Host "Checking speech model files: $Model" -ForegroundColor Cyan
    $DownloadUrl = "http://localhost:8001/v1/models/$Model"
    Invoke-RestMethod -Method Post -Uri $DownloadUrl -TimeoutSec 1800 | Out-Null
    Write-Host "Speech model ready: $Model" -ForegroundColor DarkGreen
}

Push-Location $ProjectRoot
try {
    Write-Host "Starting Postgres and the local speech service..." -ForegroundColor Cyan
    & $Docker compose up -d postgres speaches

    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3 | Out-Null
    } catch {
        Write-Host "Starting native Ollama..." -ForegroundColor Cyan
        Start-Process -FilePath $Ollama -ArgumentList "serve" -WindowStyle Hidden
    }

    Wait-ForUrl "http://localhost:11434/api/tags"
    Wait-ForUrl "http://localhost:8001/health"

    foreach ($Model in @("qwen3:4b", "nomic-embed-text")) {
        Write-Host "Downloading Ollama model: $Model" -ForegroundColor Cyan
        $Body = @{ model = $Model; stream = $false } | ConvertTo-Json
        Invoke-RestMethod -Method Post -Uri "http://localhost:11434/api/pull" -ContentType "application/json" -Body $Body -TimeoutSec 1800 | Out-Null
    }

    foreach ($Model in @(
        "Systran/faster-distil-whisper-small.en",
        "speaches-ai/Kokoro-82M-v1.0-ONNX"
    )) {
        Ensure-SpeechModel -Model $Model
    }

    Write-Host "Warming up the local evaluation model..." -ForegroundColor Cyan
    $Warmup = @{
        model = "qwen3:4b"
        messages = @(@{ role = "user"; content = "Reply with the word ready." })
        stream = $false
        think = $false
        keep_alive = "60m"
        options = @{ num_predict = 8; temperature = 0 }
    } | ConvertTo-Json -Depth 6
    Invoke-RestMethod -Method Post -Uri "http://localhost:11434/api/chat" -ContentType "application/json" -Body $Warmup -TimeoutSec 300 | Out-Null

    if (Test-Path -LiteralPath $BackendPython) {
        Write-Host "Updating the database's local embedding index..." -ForegroundColor Cyan
        Push-Location (Join-Path $ProjectRoot "backend")
        try {
            & $BackendPython -m db.init
        } finally {
            Pop-Location
        }
    }

    Write-Host "Local AI is ready. Start the API, worker, and frontend normally." -ForegroundColor Green
} finally {
    Pop-Location
}
