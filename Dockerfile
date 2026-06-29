FROM python:3.11-slim

# ffmpeg required by yt-dlp to merge video + audio streams into mp4
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code and web frontend
COPY server/main.py .
COPY frontend/ ./frontend/

RUN mkdir -p downloads

EXPOSE 8000

# Auto-update yt-dlp on every container start so it stays current with
# Instagram's weekly anti-bot changes, then launch
CMD yt-dlp -U --quiet 2>/dev/null || true && \
    uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
