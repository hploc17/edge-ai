@echo off
echo ===================================================
echo   Starting WebGIS FastAPI Backend Hub on port 8000...
echo   API Docs: http://localhost:8000/docs
echo ===================================================
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
