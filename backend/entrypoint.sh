#!/usr/bin/env sh
set -e

echo "[entrypoint] running database migrations..."
alembic upgrade head

echo "[entrypoint] starting gateway..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
