# Run this after activating the venv and starting the backend server
# Installs playwright browsers on first run
.
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Write-Error "Python not found"; exit 1 }
python -m pip install -r backend/requirements.txt
python -m playwright install
python tests/e2e/run_e2e.py
