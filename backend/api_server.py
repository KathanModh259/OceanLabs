from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
from urllib.parse import urlparse
import threading
import uuid
import os
import sys
import time
import asyncio
import re
import traceback
from collections import defaultdict

# Ensure we can import from the same directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import auth module
try:
    from auth import get_current_user, require_auth
    AUTH_AVAILABLE = True
except Exception as auth_import_error:
    AUTH_AVAILABLE = False
    AUTH_ERROR = str(auth_import_error)
    # In production, auth is required. This is for development fallback.
    async def get_current_user(request: Request):
        return {"sub": "anonymous", "email": "anonymous@example.com"}
    require_auth = lambda: Depends(get_current_user)

try:
    from dotenv import load_dotenv
except Exception:  # noqa: BLE001
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

try:
    from integrations import dispatch_post_meeting_integrations
except Exception as integrations_import_error:  # noqa: BLE001
    dispatch_post_meeting_integrations = None
    INTEGRATIONS_IMPORT_ERROR = str(integrations_import_error)
else:
    INTEGRATIONS_IMPORT_ERROR = ""

try:
    from integration_store import disconnect_user_integration, list_user_integrations, update_user_integration_config
    from oauth_integrations import (
        build_oauth_authorize_url,
        build_settings_redirect_url,
        consume_oauth_state,
        handle_oauth_callback,
    )
except Exception as integration_oauth_error:  # noqa: BLE001
    INTEGRATION_OAUTH_AVAILABLE = False
    INTEGRATION_OAUTH_ERROR = str(integration_oauth_error)
else:
    INTEGRATION_OAUTH_AVAILABLE = True
    INTEGRATION_OAUTH_ERROR = ""

app = FastAPI()
APP_START_TS = time.time()

PLATFORM_VALUES = {"meet", "teams", "zoom", "local"}
PLATFORM_ALIASES = {
    "google meet": "meet",
    "google_meet": "meet",
    "gmeet": "meet",
    "meet": "meet",
    "microsoft teams": "teams",
    "microsoft_teams": "teams",
    "ms teams": "teams",
    "ms_teams": "teams",
    "teams": "teams",
    "zoom": "zoom",
    "zoom meeting": "zoom",
    "zoom_meeting": "zoom",
    "local": "local",
    "offline": "local",
}
PLATFORM_HOST_RULES = {
    "meet": ["meet.google.com"],
    "teams": ["teams.microsoft.com", "teams.live.com", "teams.cloud.microsoft"],
    "zoom": ["zoom.us", "zoomgov.com", "zoom.com.cn"],
}
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
        origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
        if not origins:
            raise ValueError("FRONTEND_ORIGINS environment variable cannot be empty")
        return origins

    # In production, FRONTEND_ORIGINS is required
    env = os.environ.get("ENVIRONMENT", "").lower()
    if env != "production":
        # Development fallback - only for local testing
        return ["http://localhost:5173", "http://127.0.0.1:5173"]

    raise ValueError(
        "FRONTEND_ORIGINS must be set in production. "
        "Example: FRONTEND_ORIGINS=https://app.example.com,https://staging.example.com"
    )


def normalize_platform(platform: str) -> str:
    key = (platform or "").strip().lower()
    return PLATFORM_ALIASES.get(key, key)


def validate_meeting_url(url: str, platform: str) -> str:
    platform = normalize_platform(platform)
    normalized_url = (url or "").strip()

    if platform == "meet" and GOOGLE_MEET_CODE_REGEX.match(normalized_url):
        normalized_url = f"https://meet.google.com/{normalized_url}"
    elif normalized_url and not normalized_url.lower().startswith(("http://", "https://")):
        normalized_url = f"https://{normalized_url}"

    parsed = urlparse(normalized_url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Only valid HTTPS meeting URLs are allowed")

    host = (parsed.hostname or "").lower()
    domains = PLATFORM_HOST_RULES.get(platform, [])
    if domains:
        is_allowed = any(host == domain or host.endswith(f".{domain}") for domain in domains)
        if not is_allowed:
            raise HTTPException(status_code=400, detail=f"Meeting URL does not match selected platform: {platform}")

    clean_url = f"https://{parsed.netloc}{parsed.path or ''}"
    if parsed.query:
        clean_url = f"{clean_url}?{parsed.query}"
    return clean_url


def enforce_rate_limit(user_id: str):
    now = time.time()
    history = [ts for ts in start_request_history[user_id] if now - ts < RATE_LIMIT_WINDOW_SECONDS]
    if len(history) >= RATE_LIMIT_MAX_STARTS:
        raise HTTPException(status_code=429, detail="Too many start requests. Please wait a minute and try again.")
    history.append(now)
    start_request_history[user_id] = history

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


@app.get("/api/health")
@app.get("/api/healthz")
async def health_check():
    total_sessions = len(active_recordings)
    active_sessions = sum(
        1
        for info in active_recordings.values()
        if (info.get("status") or "").lower() in {"recording", "stopping", "transcribing"}
    )

    return {
        "status": "ok",
        "service": "oceanlabs-backend",
        "uptime_seconds": round(time.time() - APP_START_TS, 2),
        "active_recordings": active_sessions,
        "known_sessions": total_sessions,
        "timestamp": int(time.time() * 1000),
    }

# In-memory store of active recording sessions
active_recordings = {}
recording_stream_subscribers = defaultdict(set)
recording_stream_lock = threading.Lock()
recording_stream_loop = None


def _set_recording_stream_loop(loop):
    global recording_stream_loop
    with recording_stream_lock:
        recording_stream_loop = loop


def _register_recording_stream(recording_id: str, queue: asyncio.Queue):
    with recording_stream_lock:
        recording_stream_subscribers[recording_id].add(queue)


def _unregister_recording_stream(recording_id: str, queue: asyncio.Queue):
    with recording_stream_lock:
        subscribers = recording_stream_subscribers.get(recording_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            recording_stream_subscribers.pop(recording_id, None)


def _build_stream_snapshot(recording_id: str, info: dict) -> dict:
    return {
        "type": "snapshot",
        "recording_id": recording_id,
        "status": info.get("status"),
        "active_speaker": info.get("active_speaker"),
        "participants": info.get("participants") or [],
        "elapsed_seconds": info.get("elapsed_seconds") or 0.0,
        "last_audio_rms": info.get("last_audio_rms") or 0.0,
        "caption_text": info.get("latest_caption_text") or "",
        "timestamp": int(time.time() * 1000),
    }


def publish_recording_event(recording_id: str, payload: dict):
    if not isinstance(payload, dict):
        return

    info = active_recordings.get(recording_id) or {}
    event = {
        "recording_id": recording_id,
        "status": info.get("status"),
        "timestamp": int(time.time() * 1000),
    }
    event.update(payload)

    with recording_stream_lock:
        loop = recording_stream_loop
        subscribers = list(recording_stream_subscribers.get(recording_id, set()))

    if not loop or not subscribers:
        return

    def enqueue(queue: asyncio.Queue, message: dict):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(message)
            except Exception:
                pass
        except Exception:
            pass

    for queue in subscribers:
        try:
            loop.call_soon_threadsafe(enqueue, queue, event)
        except Exception:
            continue

class StartRecordingRequest(BaseModel):
    title: str
    platform: str  # "meet", "teams", "zoom", "local"
    url: Optional[str] = None  # Required for online platforms
    language: str = "Auto"
    duration_minutes: Optional[float] = None  # For local mode
    manual_stop: bool = False  # For local mode: start now, stop via API
    # user_id is no longer accepted from client - comes from JWT


class IntegrationSmokeTestRequest(BaseModel):
    title: str = "Website Integration Smoke"
    platform: str = "local"
    language: str = "en"
    user_id: Optional[str] = None


class IntegrationConfigUpdateRequest(BaseModel):
    user_id: str
    provider: str
    config: dict


class IntegrationDisconnectRequest(BaseModel):
    user_id: str
    provider: str


def _safe_connection_config(connection: Optional[dict]) -> dict:
    if not connection:
        return {}
    config = connection.get("config")
    if isinstance(config, dict):
        return config
    return {}


def integration_configuration_status(user_id: Optional[str] = None) -> dict:
    safe_user_id = (user_id or "").strip() or None

    if safe_user_id and INTEGRATION_OAUTH_AVAILABLE:
        user_connections = list_user_integrations(safe_user_id)

        slack_connection = user_connections.get("slack")
        slack_config = _safe_connection_config(slack_connection)
        slack_connected = bool((slack_connection or {}).get("connected")) and bool((slack_connection or {}).get("access_token"))
        slack_channel_id = (slack_config.get("channel_id") or "").strip()
        slack_ready = bool(slack_connected and slack_channel_id)
        slack_state = {
            "configured": slack_ready,
            "oauth_connected": slack_connected,
            "mode": "oauth",
            "message": (
                "Slack connected and ready for posting."
                if slack_ready
                else "Slack connected. Set channel_id to enable posting."
                if slack_connected
                else "Slack is not connected for this user."
            ),
            "config": {
                "channel_id": slack_channel_id,
                "channel_name": (slack_config.get("channel_name") or "").strip(),
            },
        }

        jira_connection = user_connections.get("jira")
        jira_config = _safe_connection_config(jira_connection)
        jira_connected = bool((jira_connection or {}).get("connected")) and bool((jira_connection or {}).get("access_token"))
        jira_cloud_id = (jira_config.get("cloud_id") or "").strip()
        jira_project_key = (jira_config.get("project_key") or "").strip()
        jira_ready = bool(jira_connected and jira_cloud_id and jira_project_key)
        jira_state = {
            "configured": jira_ready,
            "oauth_connected": jira_connected,
            "mode": "oauth",
            "message": (
                "Jira connected and ready for issue creation."
                if jira_ready
                else "Jira connected. Set project_key to enable issue creation."
                if jira_connected
                else "Jira is not connected for this user."
            ),
            "config": {
                "cloud_id": jira_cloud_id,
                "resource_url": (jira_config.get("resource_url") or "").strip(),
                "resource_name": (jira_config.get("resource_name") or "").strip(),
                "project_key": jira_project_key,
                "issue_type": (jira_config.get("issue_type") or "Task").strip() or "Task",
            },
        }

        notion_connection = user_connections.get("notion")
        notion_config = _safe_connection_config(notion_connection)
        notion_connected = bool((notion_connection or {}).get("connected")) and bool((notion_connection or {}).get("access_token"))
        notion_database_id = (notion_config.get("database_id") or "").strip()
        notion_parent_page_id = (notion_config.get("parent_page_id") or "").strip()
        notion_ready = bool(notion_connected and (notion_database_id or notion_parent_page_id))
        notion_state = {
            "configured": notion_ready,
            "oauth_connected": notion_connected,
            "mode": "oauth",
            "message": (
                "Notion connected and ready for page creation."
                if notion_ready
                else "Notion connected. Set database_id or parent_page_id to enable publishing."
                if notion_connected
                else "Notion is not connected for this user."
            ),
            "config": {
                "database_id": notion_database_id,
                "parent_page_id": notion_parent_page_id,
                "title_property": (notion_config.get("title_property") or "Name").strip() or "Name",
                "workspace_name": (notion_config.get("workspace_name") or "").strip(),
            },
        }

        services = {
            "slack": slack_state,
            "jira": jira_state,
            "notion": notion_state,
        }
        ready_count = sum(1 for service in services.values() if service["configured"])

        return {
            "source": "user-oauth",
            "services": services,
            "ready_count": ready_count,
            "total_count": len(services),
        }

    slack_webhook_url = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    slack_token = (os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_TOKEN") or "").strip()
    slack_channel_id = (os.environ.get("SLACK_CHANNEL_ID") or "").strip()

    if slack_webhook_url:
        slack_state = {
            "configured": True,
            "mode": "webhook",
            "message": "Slack configured via webhook URL.",
            "config": {"channel_id": slack_channel_id, "channel_name": ""},
        }
    elif slack_token and slack_channel_id:
        slack_state = {
            "configured": True,
            "mode": "token",
            "message": "Slack configured via bot token + channel.",
            "config": {"channel_id": slack_channel_id, "channel_name": ""},
        }
    elif slack_token:
        slack_state = {
            "configured": False,
            "mode": "incomplete",
            "message": "Slack token exists but SLACK_CHANNEL_ID is missing.",
            "config": {"channel_id": "", "channel_name": ""},
        }
    else:
        slack_state = {
            "configured": False,
            "mode": "none",
            "message": "Slack is not configured.",
            "config": {"channel_id": "", "channel_name": ""},
        }

    jira_url = (os.environ.get("JIRA_BASE_URL") or "").strip()
    jira_email = (os.environ.get("JIRA_EMAIL") or "").strip()
    jira_token = (os.environ.get("JIRA_API_TOKEN") or "").strip()
    jira_project_key = (os.environ.get("JIRA_PROJECT_KEY") or "").strip()

    jira_ready = all([jira_url, jira_email, jira_token, jira_project_key])
    jira_state = {
        "configured": jira_ready,
        "mode": "api-token",
        "message": (
            "Jira configured with base URL, user email, API token, and project key."
            if jira_ready
            else "Jira requires JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, and JIRA_PROJECT_KEY."
        ),
        "config": {
            "resource_url": jira_url,
            "project_key": jira_project_key,
            "issue_type": (os.environ.get("JIRA_ISSUE_TYPE") or "Task").strip() or "Task",
        },
    }

    notion_token = (os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_TOKEN") or "").strip()
    notion_database_id = (os.environ.get("NOTION_DATABASE_ID") or "").strip()
    notion_parent_page_id = (os.environ.get("NOTION_PARENT_PAGE_ID") or "").strip()
    notion_ready = bool(notion_token and (notion_database_id or notion_parent_page_id))

    notion_state = {
        "configured": notion_ready,
        "mode": "database" if notion_database_id else "page" if notion_parent_page_id else "none",
        "message": (
            "Notion configured with token and target parent."
            if notion_ready
            else "Notion requires NOTION_TOKEN and one parent target (database or page)."
        ),
        "config": {
            "database_id": notion_database_id,
            "parent_page_id": notion_parent_page_id,
            "title_property": (os.environ.get("NOTION_TITLE_PROPERTY") or "Name").strip() or "Name",
        },
    }

    services = {
        "slack": slack_state,
        "jira": jira_state,
        "notion": notion_state,
    }
    ready_count = sum(1 for service in services.values() if service["configured"])

    return {
        "source": "environment",
        "services": services,
        "ready_count": ready_count,
        "total_count": len(services),
    }


def start_recording_session(
    *,
    title: str,
    platform: str,
    language: str = "Auto",
    meeting_url: Optional[str] = None,
    duration_minutes: Optional[float] = None,
    manual_stop: bool = False,
    source: str = "manual",
    metadata: Optional[dict] = None,
    current_user: dict = None,  # From auth dependency
):
    platform = normalize_platform(platform)
    if platform not in PLATFORM_VALUES:
        raise HTTPException(status_code=400, detail="Invalid platform. Use meet, teams, zoom, or local")

    safe_title = (title or "").strip()
    if not safe_title:
        raise HTTPException(status_code=400, detail="Title is required")
    if len(safe_title) > 120:
        raise HTTPException(status_code=400, detail="Title is too long")

    safe_language = (language or "Auto").strip()[:40]

    safe_url = meeting_url
    if platform in ["meet", "teams", "zoom"] and not safe_url:
        raise HTTPException(status_code=400, detail="URL required for online platform")
    if platform in ["meet", "teams", "zoom"] and safe_url:
        safe_url = validate_meeting_url(safe_url, platform)

    safe_duration = duration_minutes
    safe_manual_stop = bool(manual_stop)
    if platform == "local":
        if safe_duration is not None and (safe_duration < 0.1 or safe_duration > 240):
            raise HTTPException(status_code=400, detail="Duration must be between 0.1 and 240 minutes")
        if not safe_manual_stop and safe_duration is None:
            raise HTTPException(status_code=400, detail="Duration required for local recording")

    join_meeting_and_record_fn, record_local_fn = load_recording_runtime()
    # Create a per-recording speaker diarizer instance
    from app import SpeakerDiarizer
    diarizer = SpeakerDiarizer()

    recording_id = str(uuid.uuid4())
    stop_event = threading.Event() if platform == "local" and safe_manual_stop else None

    active_recordings[recording_id] = {
        "status": "recording",
        "platform": platform,
        "title": safe_title,
        "url": safe_url,
        "language": safe_language,
        "created_at": int(time.time()),
        "summary": "",
        "transcript": "",
        "output_filename": None,
        "stop_event": stop_event,
        "source": source,
        "metadata": metadata or {},
        "active_speaker": None,
        "participants": [],
        "elapsed_seconds": 0.0,
        "last_audio_rms": 0.0,
        "latest_caption_text": "",
    }

    def handle_live_event(payload: dict):
        info = active_recordings.get(recording_id)
        if info is None or not isinstance(payload, dict):
            return

        active_speaker = payload.get("active_speaker")
        if isinstance(active_speaker, str):
            active_speaker = active_speaker.strip()
            if active_speaker:
                info["active_speaker"] = active_speaker

        participants = payload.get("participants")
        if isinstance(participants, list):
            cleaned = sorted({str(item).strip() for item in participants if str(item).strip()})
            info["participants"] = cleaned

        elapsed_seconds = payload.get("elapsed_seconds")
        if isinstance(elapsed_seconds, (int, float)):
            info["elapsed_seconds"] = round(float(elapsed_seconds), 2)

        last_audio_rms = payload.get("last_audio_rms")
        if isinstance(last_audio_rms, (int, float)):
            info["last_audio_rms"] = round(float(last_audio_rms), 6)

        caption_text = payload.get("caption_text")
        if isinstance(caption_text, str):
            cleaned_caption = caption_text.strip()
            if cleaned_caption:
                info["latest_caption_text"] = cleaned_caption

        publish_recording_event(recording_id, payload)

    def run_bot():
        # Use authenticated user ID from JWT, ignoring any user_id from metadata
        requester_user_id = current_user.get("sub") if current_user else None
        try:
            if platform == "local":
                stop_flag = active_recordings.get(recording_id, {}).get("stop_event")
                result = record_local_fn(
                    safe_duration,
                    safe_title,
                    safe_language,
                    stop_event=stop_flag,
                    requester_user_id=requester_user_id,
                    diarizer=diarizer,
                )
            else:
                result = join_meeting_and_record_fn(
                    url=safe_url,
                    title=safe_title,
                    language=safe_language,
                    platform=platform,
                    requester_user_id=requester_user_id,
                    live_event_callback=handle_live_event,
                    diarizer=diarizer,
                )

            if isinstance(result, tuple):
                transcript_text = result[0] if len(result) > 0 else ""
                summary_text = result[1] if len(result) > 1 else ""
                output_filename = result[2] if len(result) > 2 else None

                if recording_id in active_recordings:
                    active_recordings[recording_id]["transcript"] = transcript_text or ""
                    active_recordings[recording_id]["summary"] = summary_text or ""
                    active_recordings[recording_id]["output_filename"] = output_filename

                if not output_filename:
                    raise RuntimeError(
                        "Recording pipeline finished without an output file. "
                        "Check bot auth, meeting access, and audio capture setup."
                    )

            if recording_id in active_recordings:
                active_recordings[recording_id]["status"] = "completed"
                publish_recording_event(
                    recording_id,
                    {
                        "type": "state",
                        "status": "completed",
                        "summary": active_recordings[recording_id].get("summary") or "",
                    },
                )
        except Exception as e:  # noqa: BLE001
            error_text = str(e).strip() or e.__class__.__name__
            print(f"Recording failed [{e.__class__.__name__}]: {error_text}")
            print(traceback.format_exc())
            if recording_id in active_recordings:
                active_recordings[recording_id]["status"] = "error"
                active_recordings[recording_id]["error"] = f"{e.__class__.__name__}: {error_text}"
                publish_recording_event(
                    recording_id,
                    {
                        "type": "state",
                        "status": "error",
                        "error": active_recordings[recording_id].get("error"),
                    },
                )

    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    return {"recording_id": recording_id, "status": "started"}


@app.post("/api/start-recording")
async def start_recording(
    req: StartRecordingRequest,
    request: Request,
    current_user: dict = Depends(require_auth)
):
    """Start a meeting recording in a background thread."""
    # Rate limit by authenticated user ID
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    enforce_rate_limit(user_id)
    return start_recording_session(
        title=req.title,
        platform=req.platform,
        meeting_url=req.url,
        language=req.language,
        duration_minutes=req.duration_minutes,
        manual_stop=req.manual_stop,
        source="manual",
        metadata={},  # user_id now comes from JWT, not client
        current_user=current_user,
    )

def recording_belongs_to_user(info: dict, user_id: Optional[str]) -> bool:
    if not user_id:
        return True
    metadata = info.get("metadata") or {}
    owner_user_id = (metadata.get("user_id") or "").strip()
    return owner_user_id == user_id


@app.get("/api/recordings")
async def list_recordings(
    user_id: Optional[str] = None,  # DEPRECATED: use JWT
    current_user: dict = Depends(require_auth)
):
    """List active recordings for authenticated user."""
    # Use authenticated user ID, ignore query param (backward compatibility)
    safe_user_id = current_user.get("sub")
    return [
        {
            "id": rid,
            "status": info["status"],
            "platform": info["platform"],
            "title": info["title"],
            "source": info.get("source", "manual"),
            "error": info.get("error"),
            "language": info.get("language"),
            "created_at": info.get("created_at"),
            "url": info.get("url"),
            "summary": info.get("summary"),
            "active_speaker": info.get("active_speaker"),
            "participants": info.get("participants") or [],
            "elapsed_seconds": info.get("elapsed_seconds") or 0.0,
            "last_audio_rms": info.get("last_audio_rms") or 0.0,
            "latest_caption_text": info.get("latest_caption_text") or "",
        }
        for rid, info in active_recordings.items()
        if recording_belongs_to_user(info, safe_user_id)
    ]


@app.get("/api/recordings/{recording_id}")
async def get_recording_details(
    recording_id: str,
    user_id: Optional[str] = None,  # DEPRECATED: use JWT
    current_user: dict = Depends(require_auth)
):
    """Get transcript/summary details for one recording session."""
    info = active_recordings.get(recording_id)
    if not info:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Use authenticated user ID, ignore query param
    safe_user_id = current_user.get("sub")
    if not recording_belongs_to_user(info, safe_user_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    return {
        "id": recording_id,
        "status": info.get("status"),
        "platform": info.get("platform"),
        "title": info.get("title"),
        "source": info.get("source", "manual"),
        "language": info.get("language"),
        "created_at": info.get("created_at"),
        "url": info.get("url"),
        "error": info.get("error"),
        "summary": info.get("summary"),
        "transcript": info.get("transcript"),
        "output_filename": info.get("output_filename"),
        "metadata": info.get("metadata") or {},
        "active_speaker": info.get("active_speaker"),
        "participants": info.get("participants") or [],
        "elapsed_seconds": info.get("elapsed_seconds") or 0.0,
        "last_audio_rms": info.get("last_audio_rms") or 0.0,
        "latest_caption_text": info.get("latest_caption_text") or "",
    }


@app.websocket("/api/recordings/{recording_id}/stream")
async def stream_recording_events(recording_id: str, websocket: WebSocket):
    # Authenticate via JWT token in query params
    token = (websocket.query_params.get("token") or "").strip()
    if not token:
        await websocket.close(code=4401)  # Unauthorized
        return

    try:
        payload = verify_supabase_jwt(token)
        safe_user_id = payload.get("sub")
    except HTTPException:
        await websocket.close(code=4401)  # Unauthorized
        return

    info = active_recordings.get(recording_id)
    if not info or not recording_belongs_to_user(info, safe_user_id):
        await websocket.close(code=4404)  # Not found or unauthorized
        return

    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=150)
    _set_recording_stream_loop(asyncio.get_running_loop())
    _register_recording_stream(recording_id, queue)

    try:
        snapshot = _build_stream_snapshot(recording_id, info)
        await websocket.send_json(snapshot)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                latest_info = active_recordings.get(recording_id)
                heartbeat = {
                    "type": "heartbeat",
                    "recording_id": recording_id,
                    "status": (latest_info or {}).get("status", "unknown"),
                    "elapsed_seconds": (latest_info or {}).get("elapsed_seconds") or 0.0,
                    "timestamp": int(time.time() * 1000),
                }
                await websocket.send_json(heartbeat)

                if not latest_info or (latest_info.get("status") or "").lower() in {"completed", "error"}:
                    break
                continue

            await websocket.send_json(event)
            if (event.get("status") or "").lower() in {"completed", "error"}:
                break
    except WebSocketDisconnect:
        pass
    finally:
        _unregister_recording_stream(recording_id, queue)
        try:
            await websocket.close()
        except Exception:
            pass

@app.post("/api/stop-recording/{recording_id}")
async def stop_recording(
    recording_id: str,
    user_id: Optional[str] = None,  # DEPRECATED: use JWT
    current_user: dict = Depends(require_auth)
):
    """Stop an active local recording and trigger transcription."""
    info = active_recordings.get(recording_id)
    if not info:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Use authenticated user ID, ignore query param
    safe_user_id = current_user.get("sub")
    if not recording_belongs_to_user(info, safe_user_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    status = (info.get("status") or "").lower()
    if status in {"completed", "error"}:
        return {"recording_id": recording_id, "status": status}

    if info.get("platform") != "local":
        raise HTTPException(status_code=400, detail="Stop is currently supported only for local recordings")

    stop_event = info.get("stop_event")
    if stop_event is None:
        raise HTTPException(status_code=400, detail="This recording does not support manual stop")

    stop_event.set()
    info["status"] = "stopping"
    publish_recording_event(recording_id, {"type": "state", "status": "stopping"})
    return {"recording_id": recording_id, "status": "stopping"}


@app.get("/api/integrations/status")
async def get_integrations_status(
    user_id: Optional[str] = None,  # DEPRECATED: use JWT
    current_user: dict = Depends(require_auth)
):
    safe_user_id = current_user.get("sub")

    if dispatch_post_meeting_integrations is None:
        return {
            "available": False,
            "import_error": INTEGRATIONS_IMPORT_ERROR,
            "oauth_available": INTEGRATION_OAUTH_AVAILABLE,
            "oauth_error": INTEGRATION_OAUTH_ERROR,
            **integration_configuration_status(safe_user_id),
        }

    return {
        "available": True,
        "oauth_available": INTEGRATION_OAUTH_AVAILABLE,
        "oauth_error": INTEGRATION_OAUTH_ERROR,
        **integration_configuration_status(safe_user_id),
    }


@app.get("/api/integrations/oauth/{provider}/start")
async def start_integration_oauth(
    provider: str,
    user_id: Optional[str] = None,  # DEPRECATED: use JWT
    next_url: Optional[str] = None,
    current_user: dict = Depends(require_auth)
):
    if not INTEGRATION_OAUTH_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail=(
                "OAuth integrations are unavailable on backend. "
                f"Details: {INTEGRATION_OAUTH_ERROR or 'unknown error'}"
            ),
        )

    # Use authenticated user ID
    authenticated_user_id = current_user.get("sub")
    if not authenticated_user_id:
        raise HTTPException(status_code=401, detail="Could not determine authenticated user")

    try:
        ok, payload = build_oauth_authorize_url(provider, authenticated_user_id, next_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not ok:
        raise HTTPException(status_code=400, detail=payload.get("error", "Could not start OAuth flow"))

    return payload


@app.get("/api/integrations/oauth/{provider}/callback")
async def integration_oauth_callback(
    provider: str,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    safe_provider = (provider or "").strip().lower()

    if not INTEGRATION_OAUTH_AVAILABLE:
        redirect_url = build_settings_redirect_url(
            None,
            safe_provider,
            "error",
            "OAuth integrations are unavailable on backend",
        )
        return RedirectResponse(url=redirect_url, status_code=302)

    if error:
        state_entry = None
        try:
            state_entry = consume_oauth_state(safe_provider, state)
        except ValueError:
            state_entry = None

        redirect_url = build_settings_redirect_url(
            (state_entry or {}).get("next_url"),
            safe_provider,
            "error",
            (error_description or error or "OAuth authorization was denied").strip(),
        )
        return RedirectResponse(url=redirect_url, status_code=302)

    try:
        ok, payload = await handle_oauth_callback(safe_provider, code, state)
    except ValueError as exc:
        redirect_url = build_settings_redirect_url(None, safe_provider, "error", str(exc))
        return RedirectResponse(url=redirect_url, status_code=302)

    redirect_url = build_settings_redirect_url(
        payload.get("next_url"),
        payload.get("provider") or safe_provider,
        "success" if ok else "error",
        payload.get("message") or payload.get("error") or "OAuth flow completed",
    )
    return RedirectResponse(url=redirect_url, status_code=302)


@app.post("/api/integrations/config")
async def save_integration_config(
    req: IntegrationConfigUpdateRequest,
    current_user: dict = Depends(require_auth)
):
    if not INTEGRATION_OAUTH_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail=(
                "Integration config service is unavailable on backend. "
                f"Details: {INTEGRATION_OAUTH_ERROR or 'unknown error'}"
            ),
        )

    # Use authenticated user ID, ignore request.user_id for security
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    ok, detail = update_user_integration_config(user_id, req.provider, req.config)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)

    return {"status": "saved", "provider": req.provider, "user_id": user_id}


@app.post("/api/integrations/disconnect")
async def disconnect_integration(
    req: IntegrationDisconnectRequest,
    current_user: dict = Depends(require_auth)
):
    if not INTEGRATION_OAUTH_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail=(
                "Integration config service is unavailable on backend. "
                f"Details: {INTEGRATION_OAUTH_ERROR or 'unknown error'}"
            ),
        )

    # Use authenticated user ID, ignore request.user_id for security
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    ok, detail = disconnect_user_integration(user_id, req.provider)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)

    return {"status": "disconnected", "provider": req.provider, "user_id": user_id}


@app.post("/api/integrations/test")
async def run_integrations_test(
    req: IntegrationSmokeTestRequest,
    current_user: dict = Depends(require_auth)
):
    if dispatch_post_meeting_integrations is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Integrations module is unavailable. "
                f"Details: {INTEGRATIONS_IMPORT_ERROR or 'unknown error'}"
            ),
        )

    safe_platform = normalize_platform(req.platform)
    if safe_platform not in PLATFORM_VALUES:
        safe_platform = "local"

    # Use authenticated user ID
    safe_user_id = current_user.get("sub")
    result = await dispatch_post_meeting_integrations(
        title=(req.title or "Website Integration Smoke").strip()[:120] or "Website Integration Smoke",
        platform=safe_platform,
        language=(req.language or "en").strip()[:40] or "en",
        summary="Integration smoke test fired from Settings in the web application.",
        transcript="Integration smoke test fired from Settings in the web application.",
        participants=["OceanLabs Assistant"],
        output_filename=None,
        requester_user_id=safe_user_id,
    )

    return {
        "status": "completed",
        "result": result,
        "configuration": integration_configuration_status(safe_user_id),
    }