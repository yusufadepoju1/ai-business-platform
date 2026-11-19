"""Build AI_Business_Automation_Platform.zip from the project, excluding secrets and caches."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "AI_Business_Automation_Platform.zip"
SKIP_DIRS = {"__pycache__", ".venv", "venv", ".pytest_cache", "node_modules", ".git", "vectors"}
SKIP_SUFFIX = {".pyc", ".db", ".sqlite3", ".log", ".faiss", ".zip"}
SKIP_NAMES = {".env"}
top = "AI_Business_Automation_Platform"
count = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if p.is_dir() or SKIP_DIRS & set(rel.parts) or p.suffix in SKIP_SUFFIX or p.name in SKIP_NAMES or (p.name.startswith(".env.") and p.name != ".env.example"):
            continue
        z.write(p, f"{top}/{rel.as_posix()}")
        count += 1
print(f"Wrote {OUT} with {count} files")
