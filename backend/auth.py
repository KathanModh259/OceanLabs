"""
Authentication module for Supabase JWT verification.

This module provides FastAPI dependencies to protect routes using Supabase JWT tokens.
Tokens are verified using Supabase's public JWKS keys with caching.
"""
import os
import time
import hashlib
import threading
from typing import Optional, Dict, Any

import jwt
from jwt import PyJWKClient
import httpx
from fastapi import HTTPException, Depends, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Supabase project URL from environment
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL environment variable is required for JWT verification")

# JWKS endpoint URL
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
SUPABASE_AUTH_ISSUER = f"{SUPABASE_URL}/auth/v1"
SUPABASE_API_KEY = (
    os.getenv("SUPABASE_ANON_KEY", "").strip()
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
)

# Cache the JWK client (key caching handled internally by PyJWKClient)
_jwk_client: Optional[PyJWKClient] = None
_jwk_cache: Optional[Dict[str, Any]] = None
_jwk_cache_ts: float = 0
_JWK_CACHE_TTL = 300  # 5 minutes
_token_payload_cache: Dict[str, Dict[str, Any]] = {}
_token_cache_lock = threading.Lock()
_TOKEN_CACHE_MAX_ITEMS = 512


def _token_cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _extract_unverified_token_exp(token: str) -> Optional[float]:
    try:
        unverified_payload = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except Exception:
        return None

    exp = unverified_payload.get("exp")
    if isinstance(exp, (int, float)):
        return float(exp)
    return None


def _get_cached_payload(token: str) -> Optional[Dict[str, Any]]:
    cache_key = _token_cache_key(token)
    now = time.time()

    with _token_cache_lock:
        entry = _token_payload_cache.get(cache_key)
        if not entry:
            return None

        if entry.get("expires_at", 0) <= now:
            _token_payload_cache.pop(cache_key, None)
            return None

        payload = entry.get("payload")
        return dict(payload) if isinstance(payload, dict) else None


def _set_cached_payload(token: str, payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return

    exp = payload.get("exp")
    expires_at = float(exp) if isinstance(exp, (int, float)) else _extract_unverified_token_exp(token)
    if not expires_at:
        expires_at = time.time() + 300

    # Keep cache bounded to avoid unbounded memory usage under churn.
    with _token_cache_lock:
        if len(_token_payload_cache) >= _TOKEN_CACHE_MAX_ITEMS:
            _token_payload_cache.clear()

        _token_payload_cache[_token_cache_key(token)] = {
            "payload": dict(payload),
            "expires_at": float(expires_at),
        }


def _verify_via_supabase_userinfo(token: str) -> Optional[Dict[str, Any]]:
    """Fallback verification path using Supabase Auth API.

    This supports projects where session tokens are not verifiable via JWKS in local code.
    """
    if not SUPABASE_API_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": SUPABASE_API_KEY,
    }

    response = None
    for timeout_seconds in (8.0, 12.0):
        try:
            candidate = httpx.get(f"{SUPABASE_URL}/auth/v1/user", headers=headers, timeout=timeout_seconds)
        except Exception:
            continue

        response = candidate
        if candidate.status_code == 200:
            break

        # Retry once on transient upstream/server failures.
        if candidate.status_code >= 500:
            continue
        break

    if response is None or response.status_code != 200:
        return None

    try:
        data = response.json()
    except Exception:
        return None

    user_id = (data.get("id") or "").strip()
    if not user_id:
        return None

    # Normalize shape to match JWT payload fields used by the backend.
    payload = {
        "sub": user_id,
        "email": data.get("email"),
        "role": data.get("role") or "authenticated",
        "aud": data.get("aud") or "authenticated",
        "iss": SUPABASE_AUTH_ISSUER,
    }

    unverified_exp = _extract_unverified_token_exp(token)
    if unverified_exp:
        payload["exp"] = unverified_exp

    return payload

def _get_jwk_client() -> PyJWKClient:
    """Get or create the JWK client with caching."""
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(JWKS_URL)
    return _jwk_client

def verify_supabase_jwt(token: str) -> Dict[str, Any]:
    """
    Verify a Supabase JWT token and return the decoded payload.

    Raises:
        HTTPException: If token is invalid, expired, or verification fails.
    """
    cached_payload = _get_cached_payload(token)
    if cached_payload is not None:
        return cached_payload

    try:
        # Get signing key from JWKS (with caching)
        payload = None
        jwk_error = None

        try:
            jwk_client = _get_jwk_client()
            signing_key = jwk_client.get_signing_key_from_jwt(token)

            # Supabase issuer is typically {SUPABASE_URL}/auth/v1.
            for issuer in (
                SUPABASE_AUTH_ISSUER,
                f"{SUPABASE_AUTH_ISSUER}/",
                SUPABASE_URL,
                f"{SUPABASE_URL}/",
            ):
                try:
                    payload = jwt.decode(
                        token,
                        signing_key.key,
                        algorithms=["RS256"],
                        options={"verify_aud": False},
                        issuer=issuer,
                        leeway=30,
                    )
                    break
                except jwt.InvalidIssuerError:
                    continue

            if payload is not None:
                _set_cached_payload(token, payload)
                return payload
        except Exception as exc:
            jwk_error = exc

        # Fallback for projects/tokens not resolvable via JWKS path.
        fallback_payload = _verify_via_supabase_userinfo(token)
        if fallback_payload is not None:
            _set_cached_payload(token, fallback_payload)
            return fallback_payload

        # Surface JWKS error details if available for easier debugging.
        if jwk_error is not None:
            raise jwt.InvalidTokenError(str(jwk_error))
        raise jwt.InvalidTokenError("Token verification failed")
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> Dict[str, Any]:
    """
    FastAPI dependency to get the current authenticated user from JWT.

    Usage:
        @app.get("/api/recordings")
        async def list_recordings(
            current_user: dict = Depends(get_current_user)
        ):
            user_id = current_user["sub"]
            ...
    """
    # For WebSocket connections, token may be in query params
    if request.method == "GET" and "ws" in request.url.path.lower():
        token = request.query_params.get("token", "").strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    else:
        # For regular HTTP, use Authorization header
        if not credentials or not credentials.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = credentials.credentials

    payload = verify_supabase_jwt(token)
    return payload

async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
) -> Dict[str, Any]:
    """
    FastAPI dependency that enforces authentication.

    Usage:
        current_user: dict = Depends(require_auth)
    """
    return await get_current_user(request, credentials)
