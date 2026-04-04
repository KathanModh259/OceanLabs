from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from integration_store import (
    get_user_integration,
    sanitize_provider_config,
    upsert_user_integration,
)

SUPPORTED_OAUTH_PROVIDERS = {"slack", "jira", "notion"}
STATE_TTL_SECONDS = 900

_oauth_state_store: dict[str, dict] = {}


def _backend_public_base_url() -> str:
    value = (os.environ.get("BACKEND_PUBLIC_BASE_URL") or "http://localhost:8000").strip()
    return value.rstrip("/")


def _frontend_public_base_url() -> str:
    value = (os.environ.get("FRONTEND_PUBLIC_BASE_URL") or "http://localhost:5173").strip()
    return value.rstrip("/")


def _normalize_provider(provider: str) -> str:
    safe = (provider or "").strip().lower()
    if safe not in SUPPORTED_OAUTH_PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    return safe


def _get_redirect_uri(provider: str) -> str:
    safe_provider = _normalize_provider(provider)
    env_key = f"{safe_provider.upper()}_OAUTH_REDIRECT_URI"
    explicit = (os.environ.get(env_key) or "").strip()
    if explicit:
        return explicit
    return f"{_backend_public_base_url()}/api/integrations/oauth/{safe_provider}/callback"


def _merge_query(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        query[key] = value
    return urlunparse(parsed._replace(query=urlencode(query)))


def _sanitize_next_url(next_url: Optional[str]) -> str:
    default_url = f"{_frontend_public_base_url()}/settings"
    candidate = (next_url or "").strip()
    if not candidate:
        return default_url

    try:
        parsed_default = urlparse(default_url)
        parsed_candidate = urlparse(candidate)
        if parsed_candidate.scheme not in {"http", "https"}:
            return default_url
        if parsed_candidate.netloc != parsed_default.netloc:
            return default_url
        return candidate
    except Exception:  # noqa: BLE001
        return default_url


def _store_state(provider: str, user_id: str, next_url: Optional[str], redirect_uri: str) -> str:
    state = uuid.uuid4().hex
    _oauth_state_store[state] = {
        "provider": provider,
        "user_id": user_id,
        "next_url": _sanitize_next_url(next_url),
        "redirect_uri": redirect_uri,
        "created_at": int(time.time()),
    }
    return state


def consume_oauth_state(provider: str, state: Optional[str]) -> Optional[dict]:
    safe_provider = _normalize_provider(provider)
    safe_state = (state or "").strip()
    if not safe_state:
        return None

    stored = _oauth_state_store.pop(safe_state, None)
    if not stored:
        return None

    if stored.get("provider") != safe_provider:
        return None

    age_seconds = int(time.time()) - int(stored.get("created_at") or 0)
    if age_seconds > STATE_TTL_SECONDS:
        return None

    return stored


def build_oauth_authorize_url(provider: str, user_id: str, next_url: Optional[str]) -> tuple[bool, dict]:
    safe_provider = _normalize_provider(provider)
    safe_user_id = (user_id or "").strip()
    if not safe_user_id:
        return False, {"error": "user_id is required"}

    redirect_uri = _get_redirect_uri(safe_provider)
    state = _store_state(safe_provider, safe_user_id, next_url, redirect_uri)

    if safe_provider == "slack":
        client_id = (os.environ.get("SLACK_OAUTH_CLIENT_ID") or "").strip()
        if not client_id:
            return False, {"error": "SLACK_OAUTH_CLIENT_ID is missing on backend"}

        scopes = (os.environ.get("SLACK_OAUTH_SCOPES") or "chat:write,chat:write.public,channels:read,groups:read").strip()
        user_scope = (os.environ.get("SLACK_OAUTH_USER_SCOPES") or "").strip()

        params = {
            "client_id": client_id,
            "scope": scopes,
            "redirect_uri": redirect_uri,
            "state": state,
        }
        if user_scope:
            params["user_scope"] = user_scope

        auth_url = f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"

    elif safe_provider == "jira":
        client_id = (os.environ.get("JIRA_OAUTH_CLIENT_ID") or "").strip()
        if not client_id:
            return False, {"error": "JIRA_OAUTH_CLIENT_ID is missing on backend"}

        audience = (os.environ.get("JIRA_OAUTH_AUDIENCE") or "api.atlassian.com").strip()
        scopes = (os.environ.get("JIRA_OAUTH_SCOPES") or "write:jira-work read:jira-user offline_access read:me").strip()

        params = {
            "audience": audience,
            "client_id": client_id,
            "scope": scopes,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "prompt": "consent",
        }
        auth_url = f"https://auth.atlassian.com/authorize?{urlencode(params)}"

    else:
        client_id = (os.environ.get("NOTION_OAUTH_CLIENT_ID") or "").strip()
        if not client_id:
            return False, {"error": "NOTION_OAUTH_CLIENT_ID is missing on backend"}

        params = {
            "owner": "user",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
        auth_url = f"https://api.notion.com/v1/oauth/authorize?{urlencode(params)}"

    return True, {
        "provider": safe_provider,
        "authorization_url": auth_url,
        "state": state,
        "redirect_uri": redirect_uri,
    }


def _select_jira_resource(resources: list[dict]) -> Optional[dict]:
    if not resources:
        return None

    preferred_base = (os.environ.get("JIRA_BASE_URL") or "").strip().rstrip("/")
    if preferred_base:
        for resource in resources:
            if (resource.get("url") or "").rstrip("/") == preferred_base:
                return resource

    return resources[0]


async def _exchange_slack(code: str, state_entry: dict) -> tuple[bool, dict]:
    client_id = (os.environ.get("SLACK_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("SLACK_OAUTH_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        return False, {"error": "Slack OAuth client ID/secret is missing"}

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": state_entry["redirect_uri"],
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post("https://slack.com/api/oauth.v2.access", data=payload)

    if response.status_code != 200:
        return False, {"error": f"Slack OAuth exchange failed: HTTP {response.status_code}"}

    data = response.json()
    if not data.get("ok"):
        return False, {"error": f"Slack OAuth exchange failed: {data.get('error', 'unknown_error')}"}

    access_token = (data.get("access_token") or "").strip()
    if not access_token:
        return False, {"error": "Slack OAuth did not return an access token"}

    existing = get_user_integration(state_entry["user_id"], "slack") or {}
    base_config = existing.get("config") if isinstance(existing.get("config"), dict) else {}
    incoming_webhook = data.get("incoming_webhook") or {}

    merged_config = {
        **base_config,
        **sanitize_provider_config(
            "slack",
            {
                "channel_id": incoming_webhook.get("channel_id") or base_config.get("channel_id") or "",
                "channel_name": incoming_webhook.get("channel") or base_config.get("channel_name") or "",
            },
        ),
    }

    ok, detail = upsert_user_integration(
        user_id=state_entry["user_id"],
        provider="slack",
        connected=True,
        access_token=access_token,
        refresh_token=(data.get("refresh_token") or "").strip() or None,
        token_type=(data.get("token_type") or "").strip() or None,
        scope=(data.get("scope") or "").strip() or None,
        expires_in_seconds=int(data.get("expires_in")) if str(data.get("expires_in") or "").isdigit() else None,
        config=merged_config,
        external_account_id=(data.get("team") or {}).get("id"),
        external_workspace=(data.get("team") or {}).get("name"),
    )

    if not ok:
        return False, {"error": f"Could not store Slack connection: {detail}"}

    return True, {"message": "Slack connected successfully"}


async def _exchange_jira(code: str, state_entry: dict) -> tuple[bool, dict]:
    client_id = (os.environ.get("JIRA_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("JIRA_OAUTH_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        return False, {"error": "Jira OAuth client ID/secret is missing"}

    token_payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": state_entry["redirect_uri"],
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        token_response = await client.post("https://auth.atlassian.com/oauth/token", json=token_payload)

    if token_response.status_code not in {200, 201}:
        return False, {"error": f"Jira OAuth exchange failed: HTTP {token_response.status_code}"}

    token_data = token_response.json()
    access_token = (token_data.get("access_token") or "").strip()
    if not access_token:
        return False, {"error": "Jira OAuth did not return an access token"}

    async with httpx.AsyncClient(timeout=20.0) as client:
        resources_response = await client.get(
            "https://api.atlassian.com/oauth/token/accessible-resources",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if resources_response.status_code != 200:
        return False, {"error": "Jira OAuth succeeded but could not list accessible resources"}

    resources = resources_response.json() if isinstance(resources_response.json(), list) else []
    selected = _select_jira_resource(resources)
    if not selected:
        return False, {"error": "No accessible Jira cloud resource found for this account"}

    existing = get_user_integration(state_entry["user_id"], "jira") or {}
    base_config = existing.get("config") if isinstance(existing.get("config"), dict) else {}

    merged_config = {
        **base_config,
        **sanitize_provider_config(
            "jira",
            {
                "cloud_id": selected.get("id") or "",
                "resource_url": selected.get("url") or "",
                "resource_name": selected.get("name") or "",
                "project_key": base_config.get("project_key") or (os.environ.get("JIRA_PROJECT_KEY") or "").strip(),
                "issue_type": base_config.get("issue_type") or (os.environ.get("JIRA_ISSUE_TYPE") or "Task").strip() or "Task",
            },
        ),
    }

    ok, detail = upsert_user_integration(
        user_id=state_entry["user_id"],
        provider="jira",
        connected=True,
        access_token=access_token,
        refresh_token=(token_data.get("refresh_token") or "").strip() or None,
        token_type=(token_data.get("token_type") or "").strip() or "Bearer",
        scope=(token_data.get("scope") or "").strip() or None,
        expires_in_seconds=int(token_data.get("expires_in")) if str(token_data.get("expires_in") or "").isdigit() else None,
        config=merged_config,
        external_account_id=(selected.get("id") or "").strip() or None,
        external_workspace=(selected.get("name") or "").strip() or None,
    )

    if not ok:
        return False, {"error": f"Could not store Jira connection: {detail}"}

    return True, {"message": "Jira connected successfully"}


async def _exchange_notion(code: str, state_entry: dict) -> tuple[bool, dict]:
    client_id = (os.environ.get("NOTION_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("NOTION_OAUTH_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        return False, {"error": "Notion OAuth client ID/secret is missing"}

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": state_entry["redirect_uri"],
    }
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/json",
        "Notion-Version": (os.environ.get("NOTION_VERSION") or "2022-06-28").strip() or "2022-06-28",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post("https://api.notion.com/v1/oauth/token", headers=headers, json=payload)

    if response.status_code not in {200, 201}:
        return False, {"error": f"Notion OAuth exchange failed: HTTP {response.status_code}"}

    data = response.json()
    access_token = (data.get("access_token") or "").strip()
    if not access_token:
        return False, {"error": "Notion OAuth did not return an access token"}

    existing = get_user_integration(state_entry["user_id"], "notion") or {}
    base_config = existing.get("config") if isinstance(existing.get("config"), dict) else {}

    merged_config = {
        **base_config,
        **sanitize_provider_config(
            "notion",
            {
                "workspace_id": (data.get("workspace_id") or "").strip(),
                "workspace_name": (data.get("workspace_name") or "").strip(),
                "bot_id": (data.get("bot_id") or "").strip(),
                "database_id": base_config.get("database_id") or (os.environ.get("NOTION_DATABASE_ID") or "").strip(),
                "parent_page_id": base_config.get("parent_page_id") or (os.environ.get("NOTION_PARENT_PAGE_ID") or "").strip(),
                "title_property": base_config.get("title_property") or (os.environ.get("NOTION_TITLE_PROPERTY") or "Name").strip() or "Name",
            },
        ),
    }

    ok, detail = upsert_user_integration(
        user_id=state_entry["user_id"],
        provider="notion",
        connected=True,
        access_token=access_token,
        token_type=(data.get("token_type") or "").strip() or "bearer",
        config=merged_config,
        external_account_id=(data.get("workspace_id") or "").strip() or None,
        external_workspace=(data.get("workspace_name") or "").strip() or None,
    )

    if not ok:
        return False, {"error": f"Could not store Notion connection: {detail}"}

    return True, {"message": "Notion connected successfully"}


async def handle_oauth_callback(provider: str, code: Optional[str], state: Optional[str]) -> tuple[bool, dict]:
    safe_provider = _normalize_provider(provider)
    safe_code = (code or "").strip()
    if not safe_code:
        return False, {"error": "Missing authorization code"}

    state_entry = consume_oauth_state(safe_provider, state)
    if not state_entry:
        return False, {"error": "OAuth state is invalid or expired"}

    if safe_provider == "slack":
        ok, payload = await _exchange_slack(safe_code, state_entry)
    elif safe_provider == "jira":
        ok, payload = await _exchange_jira(safe_code, state_entry)
    else:
        ok, payload = await _exchange_notion(safe_code, state_entry)

    payload["next_url"] = state_entry.get("next_url") or f"{_frontend_public_base_url()}/settings"
    payload["provider"] = safe_provider
    return ok, payload


def build_settings_redirect_url(next_url: Optional[str], provider: str, status: str, message: str) -> str:
    safe_next = _sanitize_next_url(next_url)
    return _merge_query(
        safe_next,
        {
            "oauth": status,
            "provider": provider,
            "message": message,
        },
    )
