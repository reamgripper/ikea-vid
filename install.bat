@echo off
python -m venv .venv
call .venv\Scripts\activate
pip install .
playwright install chromium
assemblyvid doctor
echo Activate later with: .venv\Scripts\activate
