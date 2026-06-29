#!/bin/sh
set -e

echo "Updating yt-dlp to latest..."
pip install --quiet --upgrade yt-dlp

echo "Starting server..."
exec uvicorn server.main:app --host 0.0.0.0 --port 8000
