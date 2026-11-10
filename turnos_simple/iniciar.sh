#!/bin/bash
# Crea el entorno virtual (solo la primera vez), instala web.py y corre el programa.
cd "$(dirname "$0")"
if [ ! -d venv ]; then
  python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
echo "Abre http://localhost:8080"
python app.py
