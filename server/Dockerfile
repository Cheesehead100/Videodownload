FROM python:3.12-slim

# Install ffmpeg (required for merging streams + audio extraction)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python deps
COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY server/ ./server/
COPY frontend/ ./frontend/

# Auto-update yt-dlp to latest at container start (avoids stale extractors)
COPY server/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
