# One-time setup on Windows PowerShell. Run from the project root:  .\scripts\setup.ps1
$ErrorActionPreference = "Stop"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3.11+ is required. Install it from python.org and tick 'Add to PATH'." }
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    $key = & .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
    (Get-Content .env) -replace '^SECRET_KEY=.*', "SECRET_KEY=$key" | Set-Content .env
    Write-Host "Created .env with a new SECRET_KEY. Edit it to add DATABASE_URL and GROQ_API_KEY."
}
Write-Host "Setup complete. Next: .\scripts\run.ps1"
