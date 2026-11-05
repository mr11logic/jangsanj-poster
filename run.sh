#!/usr/bin/env bash
# Start the JangSanj poster service.
#
#   ./run.sh              # 0.0.0.0:8000
#   PORT=9000 ./run.sh    # custom port
#   HOST=127.0.0.1 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

# Auto-install deps on first run (best-effort)
if ! python3 -c "import fastapi, uvicorn, PIL, jdatetime" 2>/dev/null; then
    echo ">> Installing dependencies from requirements.txt ..."
    pip install --quiet -r requirements.txt
fi

exec python3 app.py
