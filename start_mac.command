#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3 mangler. Installer Python fra https://www.python.org/downloads/'
  read -r -p 'Tryk Enter for at afslutte...'
  exit 1
fi
python3 -m venv .venv || exit 1
source .venv/bin/activate
python -m pip install -r requirements.txt || exit 1
python -m streamlit run app.py
