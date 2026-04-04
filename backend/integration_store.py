from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

try:
    from supabase import create_client
except Exception:  # noqa: BLE001
    create_client = None  # type: ignore[assignment]

SUPPORTED_INTEGRATION_PROVIDERS = {"slack", "jira", "notion"}

ALLOWED_CONFIG_KEYS = {
    "slack": {"channel_id", "channel_name"},
    "jira": {"cloud_id", "resource_url", "resource_name", "project_key", "issue_type"},
    "notion": {"database_id", "parent_page_id", "title_property", "workspace_id", "workspace_name", "bot_id"},
}

_SUPABASE_CLIENT: Optional[Any] = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_supabase_client() -> Optional[Any]:
    global _SUPABASE_CLIENT
    if _SUPABASE_CLIENT is not None:
        return _SUPABASE_CLIENT

    if create_client is None:
        return None

    sb_url = (os.environ.get("SUPABASE_URL") or "").strip()
    sb_key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    if not sb_url or not sb_key:
        return None

    try:
        _SUPABASE_CLIENT = create_client(sb_url, sb_key)
    except Exception:  # noqa: BLE001
        _SUPABASE_CLIENT = None

    return _SUPABASE_CLIENT


def normalize_provider(provider: str) -> str:
    value = (provider or "").strip().lower()
    if value not in SUPPORTED_INTEGRATION_PROVIDERS:
        raise ValueError(f"Unsupported integration provider: {provider}")
    return value


def _safe_config(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    return {}


def sanitize_provider_config(provider: str, config: Optional[dict]) -> dict:
    safe_provider = normalize_provider(provider)
    raw = _safe_config(config)
    allowed_keys = ALLOWED_CONFIG_KEYS.get(safe_provider, set())
    sanitized = {}
    for key, val in raw.items():
        if key in allowed_keys:
            if isinstance(val, str):
                sanitized[key] = val.strip()
            else:
                sanitized[key] = val
    return sanitized


def list_user_integrations(user_id: Optional[str]) -> dict:
    safe_user_id = (user_id or "").strip()
    if not safe_user_id:
        return {}

    client = _get_supabase_client()
    if client is None:
        return {}

    try:
        response = (
            client.table("integration_connections")
            .select("*")
            .eq("user_id", safe_user_id)
            .execute()
        )
    except Exception:  # noqa: BLE001
        return {}

    rows = response.data or []
    indexed = {}
    for row in rows:
        provider = (row.get("provider") or "").strip().lower()
        if provider not in SUPPORTED_INTEGRATION_PROVIDERS:
            continue
        row["config"] = _safe_config(row.get("config"))
        indexed[provider] = row
    return indexed


def get_user_integration(user_id: str, provider: str) -> Optional[dict]:
    safe_provider = normalize_provider(provider)
    return list_user_integrations(user_id).get(safe_provider)


def upsert_user_integration(
    *,
    user_id: str,
    provider: str,
    connected: bool,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    token_type: Optional[str] = None,
    scope: Optional[str] = None,
    expires_in_seconds: Optional[int] = None,
    config: Optional[dict] = None,
    external_account_id: Optional[str] = None,
    external_workspace: Optional[str] = None,
) -> tuple[bool, str]:
    safe_user_id = (user_id or "").strip()
    if not safe_user_id:
        return False, "user_id is required"

    safe_provider = normalize_provider(provider)
    safe_config = sanitize_provider_config(safe_provider, config)

    expires_at = None
    if isinstance(expires_in_seconds, int) and expires_in_seconds > 0:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)).isoformat()

    payload = {
        "user_id": safe_user_id,
        "provider": safe_provider,
        "connected": bool(connected),
        "access_token": (access_token or "").strip() or None,
        "refresh_token": (refresh_token or "").strip() or None,
        "token_type": (token_type or "").strip() or None,
        "scope": (scope or "").strip() or None,
        "expires_at": expires_at,
        "external_account_id": (external_account_id or "").strip() or None,
        "external_workspace": (external_workspace or "").strip() or None,
        "config": safe_config,
        "updated_at": _utc_now_iso(),
    }

    client = _get_supabase_client()
    if client is None:
        return False, "Supabase is not configured on backend"

    try:
        client.table("integration_connections").upsert(payload, on_conflict="user_id,provider").execute()
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def update_user_integration_config(user_id: str, provider: str, config_updates: Optional[dict]) -> tuple[bool, str]:
    safe_provider = normalize_provider(provider)
    safe_user_id = (user_id or "").strip()
    if not safe_user_id:
        return False, "user_id is required"

    updates = sanitize_provider_config(safe_provider, config_updates)
    if not updates:
        return False, "No valid configuration values were provided"

    existing = get_user_integration(safe_user_id, safe_provider)
    base_config = _safe_config(existing.get("config") if existing else {})
    merged_config = {**base_config, **updates}

    payload = {
        "user_id": safe_user_id,
        "provider": safe_provider,
        "config": merged_config,
        "updated_at": _utc_now_iso(),
        "connected": bool(existing.get("connected")) if existing else False,
    }

    for key in [
        "access_token",
        "refresh_token",
        "token_type",
        "scope",
        "expires_at",
        "external_account_id",
        "external_workspace",
    ]:
        if existing and key in existing:
            payload[key] = existing.get(key)

    client = _get_supabase_client()
    if client is None:
        return False, "Supabase is not configured on backend"

    try:
        client.table("integration_connections").upsert(payload, on_conflict="user_id,provider").execute()
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def disconnect_user_integration(user_id: str, provider: str) -> tuple[bool, str]:
    safe_provider = normalize_provider(provider)
    safe_user_id = (user_id or "").strip()
    if not safe_user_id:
        return False, "user_id is required"

    client = _get_supabase_client()
    if client is None:
        return False, "Supabase is not configured on backend"

    try:
        (
            client.table("integration_connections")
            .delete()
            .eq("user_id", safe_user_id)
            .eq("provider", safe_provider)
            .execute()
        )
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
