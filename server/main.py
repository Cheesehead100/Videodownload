"""
Videodownload — Self-Hosted Instagram Video Downloader API
github.com/Cheesehead100/Videodownload

Stack: FastAPI + yt-dlp + ffmpeg
No rate limits. No third-party API keys. Runs anywhere.

Local:
    pip install -r requirements.txt
    python main.py

Docker:
    docker build -t videodownload .
    docker run -d -p 8000:8000 videodownload

Render / Railway: see render.yaml / README.md
"""

import os
import re
import shutil
import uuid
import time
import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import yt_dlp

# ── Config ────────────────────────────────────────────────────────────────────

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

STATIC_DIR = Path("frontend")

# Files older than this are deleted automatically (seconds)
FILE_TTL = int(os.getenv("FILE_TTL_SECONDS", 600))

# Optional API key — set env var VDLOAD_API_KEY to protect the endpoint
API_KEY = os.getenv("VDLOAD_API_KEY", "")

# Optional Instagram cookies file (Netscape format) for authenticated scraping.
# Instagram now blocks most anonymous yt-dlp requests with "empty media response".
# On Render, upload as a Secret File named "cookies.txt" — it's mounted at
# /etc/secrets/cookies.txt automatically. Override the path with COOKIES_FILE.
COOKIES_FILE = os.getenv("COOKIES_FILE", "/etc/secrets/cookies.txt")

# yt-dlp persists any updated Set-Cookie values back to the cookiefile after each
# session — but Secret Files on Render are mounted read-only. Copy to a writable
# path at startup and point yt-dlp there instead.
RUNTIME_COOKIES_FILE = DOWNLOAD_DIR / ".cookies_runtime.txt"
if Path(COOKIES_FILE).is_file():
    shutil.copy2(COOKIES_FILE, RUNTIME_COOKIES_FILE)

# Allow all origins so the iPhone Shortcut + web UI can both reach the API
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

logging.basicConfig(level=logging.INFO, format="%(levelname)s │ %(message)s")
log = logging.getLogger("videodownload")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Videodownload",
    description="Self-hosted Instagram video downloader — github.com/Cheesehead100/Videodownload",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Serve the web frontend from /frontend
if STATIC_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")

# ── Models ────────────────────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    url: str
    quality: Optional[str] = "720p"   # best | 720p | 480p | 360p | audio
    api_key: Optional[str] = None

class DownloadResponse(BaseModel):
    status: str
    download_url: str
    stream_url: str
    filename: str
    file_size_mb: Optional[float] = None
    duration_seconds: Optional[int] = None
    title: Optional[str] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None

class InfoResponse(BaseModel):
    title: Optional[str]
    uploader: Optional[str]
    duration_seconds: Optional[int]
    thumbnail: Optional[str]
    upload_date: Optional[str]
    view_count: Optional[int]
    like_count: Optional[int]
    available_qualities: list

# ── Helpers ───────────────────────────────────────────────────────────────────

INSTAGRAM_RE = re.compile(
    r"https?://(www\.)?instagram\.com/(p|reel|tv|stories|clips)/[\w\-]+"
)

def validate_instagram_url(url: str):
    if not INSTAGRAM_RE.match(url.strip()):
        raise HTTPException(
            status_code=400,
            detail="Must be an instagram.com post, reel, TV, or story URL"
        )

def auth_check(key: Optional[str]):
    if API_KEY and key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4 Mobile/15E148 Safari/604.1"
)

def cookie_opts() -> dict:
    """Attach Instagram session cookies if a cookies file is present."""
    if RUNTIME_COOKIES_FILE.is_file():
        return {"cookiefile": str(RUNTIME_COOKIES_FILE)}
    return {}


def ydl_opts(out_dir: Path, quality: str) -> dict:
    fmt = {
        "best":  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "720p":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
        "480p":  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]",
        "360p":  "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best[height<=360]",
        "audio": "bestaudio[ext=m4a]/bestaudio",
    }.get(quality, "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]")

    return {
        "format": fmt,
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "retries": 4,
        "fragment_retries": 4,
        "http_headers": {"User-Agent": MOBILE_UA},
        # merge into a single mp4 (requires ffmpeg)
        "merge_output_format": "mp4",
        "postprocessors": [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }],
        **cookie_opts(),
    }

async def run_in_thread(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)

def _do_download(url: str, opts: dict) -> dict:
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)

def _do_info(url: str) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "http_headers": {"User-Agent": MOBILE_UA},
        **cookie_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def purge_old_files():
    now = time.time()
    for session_dir in DOWNLOAD_DIR.iterdir():
        if session_dir.is_dir():
            try:
                age = now - session_dir.stat().st_mtime
                if age > FILE_TTL:
                    for f in session_dir.iterdir():
                        f.unlink(missing_ok=True)
                    session_dir.rmdir()
            except Exception:
                pass

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
def health():
    """Liveness check — also returns yt-dlp version."""
    return {
        "status": "ok",
        "yt_dlp_version": yt_dlp.version.__version__,
        "file_ttl_seconds": FILE_TTL,
        "cookies_configured": RUNTIME_COOKIES_FILE.is_file(),
    }


@app.get("/info", response_model=InfoResponse, tags=["download"])
async def get_info(
    url: str = Query(..., description="Instagram post/reel URL"),
    api_key: Optional[str] = Query(None),
):
    """Return video metadata without downloading. Useful for previewing."""
    auth_check(api_key)
    validate_instagram_url(url)

    try:
        info = await run_in_thread(_do_info, url)
        if not info:
            raise HTTPException(status_code=422, detail="yt-dlp returned no metadata for this URL")

        qualities = sorted(set(
            f"{f['height']}p"
            for f in info.get("formats", [])
            if f.get("height") and f.get("ext") == "mp4"
        ), key=lambda x: int(x[:-1]), reverse=True)

        d = info.get("duration")
        return InfoResponse(
            title=(info.get("title") or info.get("description", ""))[:120],
            uploader=info.get("uploader"),
            duration_seconds=int(d) if d is not None else None,
            thumbnail=info.get("thumbnail"),
            upload_date=info.get("upload_date"),
            view_count=info.get("view_count"),
            like_count=info.get("like_count"),
            available_qualities=qualities or ["720p", "480p", "360p"],
        )
    except HTTPException:
        raise
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=422, detail=f"yt-dlp: {e}")
    except Exception as e:
        log.exception("Unexpected error in /info")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/download", response_model=DownloadResponse, tags=["download"])
async def download_video(req: DownloadRequest, background_tasks: BackgroundTasks):
    """
    Download an Instagram video. Returns URLs to fetch the MP4 file.

    - `download_url` — triggers a browser file download (attachment header)
    - `stream_url`   — streams the video directly (for iPhone Shortcut / preview)
    """
    auth_check(req.api_key)
    validate_instagram_url(req.url)

    session = DOWNLOAD_DIR / str(uuid.uuid4())
    session.mkdir()

    opts = ydl_opts(session, req.quality or "720p")

    try:
        log.info(f"Download start │ {req.url} │ quality={req.quality}")
        info = await run_in_thread(_do_download, req.url, opts)

        files = list(session.iterdir())
        if not files:
            raise HTTPException(status_code=500, detail="Download succeeded but no file found")

        mp4_files = [f for f in files if f.suffix == ".mp4"]
        downloaded = mp4_files[0] if mp4_files else files[0]

        size_mb = round(downloaded.stat().st_size / (1024 * 1024), 2)
        file_id = f"{session.name}/{downloaded.name}"

        background_tasks.add_task(purge_old_files)

        log.info(f"Download done  │ {downloaded.name} │ {size_mb} MB")

        d = info.get("duration")
        return DownloadResponse(
            status="ok",
            download_url=f"/files/{file_id}?dl=1",
            stream_url=f"/files/{file_id}",
            filename=downloaded.name,
            file_size_mb=size_mb,
            duration_seconds=int(d) if d is not None else None,
            title=(info.get("title") or info.get("description", ""))[:120],
            thumbnail=info.get("thumbnail"),
            uploader=info.get("uploader"),
        )
    except HTTPException:
        shutil.rmtree(session, ignore_errors=True)
        raise
    except yt_dlp.utils.DownloadError as e:
        shutil.rmtree(session, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"yt-dlp failed: {e}")
    except Exception as e:
        log.exception("Unexpected error in /download")
        shutil.rmtree(session, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/files/{session}/{filename}", tags=["files"])
async def serve_file(session: str, filename: str, dl: int = 0):
    """
    Serve a downloaded file.
    - `?dl=1` forces a browser download (attachment)
    - Default streams inline (for direct Save-to-Photos in Shortcut)
    """
    if ".." in session or ".." in filename or "/" in session or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid path")

    path = DOWNLOAD_DIR / session / filename
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found or expired (TTL: {FILE_TTL}s). Re-download to get a fresh link."
        )

    disposition = "attachment" if dl else "inline"
    return FileResponse(
        path=path,
        media_type="video/mp4",
        filename=filename,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    log.info(f"Starting Videodownload on port {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
