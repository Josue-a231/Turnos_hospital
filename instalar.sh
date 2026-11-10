#!/bin/bash
cd "$(dirname "$0")"
unzip -oq turnos_simple.zip || python3 -m zipfile -e turnos_simple.zip .
cd turnos_simple
bash iniciar.sh
