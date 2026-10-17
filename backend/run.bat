@echo off
cd /d "%~dp0"
if not exist .venv (py -3.11 -m venv .venv)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
