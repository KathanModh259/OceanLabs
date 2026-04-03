from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from urllib.parse import urlparse
import threading
import uuid
import os
import sys
import time
import re
import traceback
from collections import defaultdict

# Ensure we can import from the same directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

app = FastAPI()

PLATFORM_VALUES = {"meet", "teams", "zoom", "local"}
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_STARTS = 4
start_request_history = defaultdict(list)
GOOGLE_MEET_CODE_REGEX = re.compile(r"^[a-z]{3}-[a-z]{4}-[a-z]{3}$", re.IGNORECASE)


def load_recording_runtime():
    try:
        from app import join_meeting_and_record, record_local
        return join_meeting_and_record, record_local
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Recording engine dependencies are missing or failed to load. "
                "Install backend requirements with: pip install -r backend/requirements.txt. "
                f"Details: {exc}"
            ),
        )


def get_allowed_origins():
    configured = os.environ.get("FRONTEND_ORIGINS", "")
    if configured.strip():
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
    ]


def validate_meeting_url(url: str, platform: str) -> str:
    normalized_url = (url or "").strip()

    if platform == "meet" and GOOGLE_MEET_CODE_REGEX.match(normalized_url):
        normalized_url = f"https://meet.google.com/{normalized_url}"
    elif normalized_url and not normalized_url.lower().startswith(("http://", "https://")):
        normalized_url = f"https://{normalized_url}"

    parsed = urlparse(normalized_url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Only valid HTTPS meeting URLs are allowed")

    host = (parsed.hostname or "").lower()
    expected_domains = {
        "meet": ["meet.google.com"],
        "teams": ["teams.microsoft.com"],
        "zoom": ["zoom.us"],
    }

    domains = expected_domains.get(platform, [])
    if domains:
        is_allowed = any(host == domain or host.endswith(f".{domain}") for domain in domains)
        if not is_allowed:
            raise HTTPException(status_code=400, detail=f"Meeting URL does not match selected platform: {platform}")

    clean_url = f"https://{parsed.netloc}{parsed.path or ''}"
    if parsed.query:
        clean_url = f"{clean_url}?{parsed.query}"
    return clean_url


def enforce_rate_limit(client_ip: str):
    now = time.time()
    history = [ts for ts in start_request_history[client_ip] if now - ts < RATE_LIMIT_WINDOW_SECONDS]
    if len(history) >= RATE_LIMIT_MAX_STARTS:
        raise HTTPException(status_code=429, detail="Too many start requests. Please wait a minute and try again.")
    history.append(now)
    start_request_history[client_ip] = history

# CORS - allow React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    return response

# In-memory store of active recording sessions
active_recordings = {}

class StartRecordingRequest(BaseModel):
    title: str
    platform: str  # "meet", "teams", "zoom", "local"
    url: Optional[str] = None  # Required for online platforms
    language: str = "Auto"
    duration_minutes: Optional[float] = None  # For local mode

@app.post("/api/start-recording")
async def start_recording(req: StartRecordingRequest, request: Request):
    """Start a meeting recording in a background thread."""
    client_ip = request.client.host if request.client and request.client.host else "unknown"
    enforce_rate_limit(client_ip)

    platform = (req.platform or "").strip().lower()
    if platform not in PLATFORM_VALUES:
        raise HTTPException(status_code=400, detail="Invalid platform. Use meet, teams, zoom, or local")

    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    if len(title) > 120:
        raise HTTPException(status_code=400, detail="Title is too long")

    language = (req.language or "Auto").strip()[:40]

    meeting_url = req.url
    if platform in ["meet", "teams", "zoom"] and not meeting_url:
        raise HTTPException(status_code=400, detail="URL required for online platform")
    if platform in ["meet", "teams", "zoom"] and meeting_url:
        meeting_url = validate_meeting_url(meeting_url, platform)

    duration_minutes = req.duration_minutes
    if platform == "local" and not duration_minutes:
        raise HTTPException(status_code=400, detail="Duration required for local recording")
    if platform == "local" and duration_minutes:
        if duration_minutes < 0.1 or duration_minutes > 240:
            raise HTTPException(status_code=400, detail="Duration must be between 0.1 and 240 minutes")

    join_meeting_and_record_fn, record_local_fn = load_recording_runtime()

    recording_id = str(uuid.uuid4())

    def run_bot():
        try:
            if platform == "local":
                result = record_local_fn(duration_minutes, title, language)
            else:
                result = join_meeting_and_record_fn(
                    url=meeting_url,
                    title=title,
                    language=language,
                    platform=platform
                )

            # Recording functions return (transcript, summary, output_filename).
            if isinstance(result, tuple):
                transcript_text = result[0] if len(result) > 0 else ""
                summary_text = result[1] if len(result) > 1 else ""
                output_filename = result[2] if len(result) > 2 else None

                if recording_id in active_recordings:
                    active_recordings[recording_id]["transcript"] = transcript_text or ""
                    active_recordings[recording_id]["summary"] = summary_text or ""
                    active_recordings[recording_id]["output_filename"] = output_filename

                # If output file is missing, treat it as a runtime failure instead of completed.
                if not output_filename:
                    raise RuntimeError("Recording pipeline finished without an output file. Check bot auth, meeting access, and audio capture setup.")

            # Mark as completed after function returns
            if recording_id in active_recordings:
                active_recordings[recording_id]["status"] = "completed"
        except Exception as e:
            error_text = str(e).strip() or e.__class__.__name__
            print(f"Recording failed [{e.__class__.__name__}]: {error_text}")
            print(traceback.format_exc())
            if recording_id in active_recordings:
                active_recordings[recording_id]["status"] = "error"
                active_recordings[recording_id]["error"] = f"{e.__class__.__name__}: {error_text}"

    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    active_recordings[recording_id] = {
        "status": "recording",
        "platform": platform,
        "title": title,
        "url": meeting_url,
        "language": language,
        "created_at": int(time.time()),
        "summary": "",
        "transcript": "",
        "output_filename": None,
    }
    return {"recording_id": recording_id, "status": "started"}

@app.get("/api/recordings")
async def list_recordings():
    """List active recordings."""
    return [
        {
            "id": rid,
            "status": info["status"],
            "platform": info["platform"],
            "title": info["title"],
            "error": info.get("error"),
            "language": info.get("language"),
            "created_at": info.get("created_at"),
            "url": info.get("url"),
            "summary": info.get("summary"),
        }
        for rid, info in active_recordings.items()
    ]


@app.get("/api/recordings/{recording_id}")
async def get_recording_details(recording_id: str):
    """Get transcript/summary details for one recording session."""
    info = active_recordings.get(recording_id)
    if not info:
        raise HTTPException(status_code=404, detail="Recording not found")

    return {
        "id": recording_id,
        "status": info.get("status"),
        "platform": info.get("platform"),
        "title": info.get("title"),
        "language": info.get("language"),
        "created_at": info.get("created_at"),
        "url": info.get("url"),
        "error": info.get("error"),
        "summary": info.get("summary"),
        "transcript": info.get("transcript"),
        "output_filename": info.get("output_filename"),
    }

@app.post("/api/stop-recording/{recording_id}")
async def stop_recording(recording_id: str):
    """Stop an active recording. (Not implemented: would need a stop flag)"""
    raise HTTPException(status_code=501, detail="Stop endpoint not implemented - use console 'q' to stop")