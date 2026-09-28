#!/bin/sh
set -e
python3 -m venv .venv
. .venv/bin/activate
pip install .
playwright install chromium
assemblyvid doctor
echo "Activate later with: . .venv/bin/activate"
