# Videodownload

Self-hosted Instagram video downloader — no rate limits, no third-party API keys, no recurring costs.

**Stack:** FastAPI + yt-dlp + ffmpeg  
**Deploy:** Render.com (free) · Railway · Docker · Any Linux VM

---

## Features

- Downloads public Instagram posts, reels, IGTV, and stories
- Quality selection: best / 720p / 480p / 360p / audio-only
- Web UI included — served at `/app`
- REST API with Swagger docs at `/docs`
- iPhone Shortcut support — saves directly to Photos, zero browser popups
- Auto-updates yt-dlp weekly via GitHub Actions to stay ahead of Instagram changes
- Optional API key protection
- Files auto-deleted after 10 minutes

---

## Quick start (local)

```bash
# Prerequisites: Python 3.10+, ffmpeg
# Install ffmpeg: brew install ffmpeg  (Mac) or  apt install ffmpeg  (Linux)

cd server
pip install -r requirements.txt
python main.py

# Server: http://localhost:8000
# Web UI: http://localhost:8000/app
# API docs: http://localhost:8000/docs
```

Test with curl:
```bash
curl -X POST http://localhost:8000/download \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.instagram.com/reel/SHORTCODE/","quality":"720p"}'
```

---

## Deploy to Render.com (free tier)

1. Fork this repo to your GitHub account
2. Go to [render.com](https://render.com) → **New** → **Blueprint**
3. Connect your fork — Render reads `render.yaml` automatically
4. Click **Apply** — deploys in ~3 minutes
5. Copy the auto-generated `VDLOAD_API_KEY` from the Environment tab

Your server will be live at `https://videodownload.onrender.com` (or similar).

> **Note:** Render's free tier sleeps after 15 min of inactivity. First request after sleep takes ~30s. Upgrade to Starter ($7/mo) for always-on.

---

## Deploy with Docker

```bash
# Build
docker build -f server/Dockerfile -t videodownload .

# Run
docker run -d \
  -p 8000:8000 \
  -e VDLOAD_API_KEY=your-secret-key \
  --name videodownload \
  --restart unless-stopped \
  videodownload
```

---

## Deploy on Azure VM (recommended for production)

```bash
# 1. SSH into your VM
# 2. Install Docker
curl -fsSL https://get.docker.com | sh

# 3. Clone the repo
git clone https://github.com/Cheesehead100/Videodownload.git
cd Videodownload

# 4. Build and run
docker build -f server/Dockerfile -t videodownload .
docker run -d -p 8000:8000 -e VDLOAD_API_KEY=your-secret --name vdload videodownload

# 5. (Optional) nginx reverse proxy + SSL
sudo apt install nginx certbot python3-certbot-nginx -y
# Configure nginx to proxy port 80/443 → 8000
```

---

## API Reference

### `POST /download`

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Instagram post/reel URL |
| `quality` | string | `best` \| `720p` \| `480p` \| `360p` \| `audio` |
| `api_key` | string | Required if `VDLOAD_API_KEY` env var is set |

Response:
```json
{
  "status": "ok",
  "download_url": "/files/uuid/video.mp4?dl=1",
  "stream_url": "/files/uuid/video.mp4",
  "filename": "video.mp4",
  "file_size_mb": 14.2,
  "duration_seconds": 30,
  "title": "Post caption...",
  "thumbnail": "https://...",
  "uploader": "username"
}
```

### `GET /info?url=...`
Returns metadata without downloading (title, thumbnail, duration, available qualities).

### `GET /health`
Returns server status and current yt-dlp version.

---

## iPhone Shortcut — auto-save to Photos

Build this shortcut once and use it forever from Instagram's Share Sheet.

### Actions (in order)

| # | Action | Settings |
|---|--------|----------|
| 1 | **Receive Input from Share Sheet** | Input type: URLs |
| 2 | **Text** | Your server URL: `https://videodownload.onrender.com` |
| 3 | **Text** | Your API key (from Render env vars) |
| 4 | **Dictionary** | Keys: `url` = Shortcut Input, `quality` = `720p`, `api_key` = Text from step 3 |
| 5 | **Get Contents of URL** | URL: combine step 2 + `/download` · Method: POST · Body: JSON → step 4 |
| 6 | **Get Dictionary Value** | Key: `stream_url` · From: step 5 result |
| 7 | **Text** | Combine step 2 + Dictionary Value (step 6) |
| 8 | **Get Contents of URL** | URL: Text from step 7 · Method: GET |
| 9 | **Save to Photo Album** | Input: step 8 result · Album: Recents |

**Final settings:** Tap ⚙ → enable **Show in Share Sheet** → Input types: URLs → Done.

**Usage:** Instagram → ··· → Share → Shortcuts → "Save IG Video" → video lands in Photos in ~5 seconds.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Server port |
| `VDLOAD_API_KEY` | *(empty)* | API key — leave empty to disable auth |
| `FILE_TTL_SECONDS` | `600` | How long downloaded files are kept |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |

---

## Keeping yt-dlp current

Instagram changes its internal APIs frequently. This repo includes a GitHub Actions workflow (`.github/workflows/update-ytdlp.yml`) that opens a weekly PR to bump yt-dlp.

The Docker container also runs `yt-dlp -U` on every start as a safety net.

For bare-metal, add a cron job:
```bash
# crontab -e
0 4 * * 1  pip install --upgrade yt-dlp
```

---

## Limitations

- Instagram now blocks most anonymous scraping, even for public reels/posts ("Instagram sent an empty media response"). Add a cookies file (below) to fix this.
- Private accounts require your own Instagram session cookie regardless.
- Downloads are **ephemeral** — files are deleted after 10 minutes.
- Stories require a logged-in session cookie in most cases.

---

## Authenticating with Instagram (cookies)

Instagram increasingly requires a logged-in session even to serve public post data to yt-dlp. If `/download` fails with `Instagram sent an empty media response`, export your Instagram session cookies and give them to the server.

1. **Export cookies** from a browser where you're logged into Instagram:
   - Chrome/Edge/Firefox extension: "Get cookies.txt LOCALLY" (or similar) — export in Netscape format for `instagram.com`.
   - Save the file as `cookies.txt`.
2. **Provide it to the server:**
   - **Render:** Dashboard → your service → **Environment** → **Secret Files** → add a file named `cookies.txt` with the exported contents. Render mounts it at `/etc/secrets/cookies.txt`, which the server reads automatically — just restart the service afterward.
   - **Docker/VM:** mount the file into the container and set `COOKIES_FILE` to its path:
     ```bash
     docker run -d -p 8000:8000 \
       -v /path/to/cookies.txt:/run/secrets/cookies.txt:ro \
       -e COOKIES_FILE=/run/secrets/cookies.txt \
       videodownload
     ```
3. **Verify:** `GET /health` returns `"cookies_configured": true` once the file is detected.

Cookies expire periodically (Instagram sessions typically last weeks) — re-export and re-upload if downloads start failing with auth errors again. Treat `cookies.txt` as a secret; it's equivalent to your Instagram login session.

---

*Not affiliated with Instagram or Meta. Use responsibly for personal use only.*
