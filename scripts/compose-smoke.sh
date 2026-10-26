#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose --env-file .env.example)
cleanup() { "${compose[@]}" down --remove-orphans; }
trap cleanup EXIT

"${compose[@]}" up --build --detach --wait api postgres
"${compose[@]}" exec -T api python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3))['status'] == 'ok'"
"${compose[@]}" exec -T api python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5))['status'] == 'ready'"
