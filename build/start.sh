#! /usr/bin/env sh
set -e

# Keep a single application process for the ephemeral JWT secret and SQLite scheduler.
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1