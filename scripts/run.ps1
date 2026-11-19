# Applies database migrations, then starts the app (API + frontend) on http://localhost:8000
param([switch]$Demo, [int]$Port = 8000)
$ErrorActionPreference = "Stop"
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run .\scripts\setup.ps1 first." }
& $py -m alembic upgrade head
if ($Demo) { & $py scripts\seed_demo.py }
& $py -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload
