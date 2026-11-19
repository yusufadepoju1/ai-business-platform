# Runs the automated test suite (uses a temporary SQLite database, no external services).
$ErrorActionPreference = "Stop"
.\.venv\Scripts\python.exe -m pytest tests -v
