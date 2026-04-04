"""
Authentication module for Supabase JWT verification.

This module provides FastAPI dependencies to protect routes using Supabase JWT tokens.
Tokens are verified using Supabase's public JWKS keys with caching.
"""
import os
import time
from typing import Optional, Dict, Any
from functools import lru_cache

import jwt
from jwt import PyJWKClient, PyJWK
from fastapi import HTTPException, Depends, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Supabase project URL from environment
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL environment variable is required for JWT verification")

# JWKS endpoint URL
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"

# Cache the JWK client (key caching handled internally by PyJWKClient)
_jwk_client: Optional[PyJWKClient] = None
_jwk_cache: Optional[Dict[str, Any]] = None
_jwk_cache_ts: float = 0
_JWK_CACHE_TTL = 300  # 5 minutes

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
    try:
        # Get signing key from JWKS (with caching)
        jwk_client = _get_jwk_client()
        signing_key = jwk_client.get_signing_key_from_jwt(token)

        # Decode and verify token
        # Supabase tokens have these standard claims
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience="authenticated",
            issuer=SUPABASE_URL,
        )
        return payload
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

def require_auth() -> Dict[str, Any]:
    """
    Dependency factory to require authentication.
    Can be used as: current_user: dict = Depends(require_auth())

    Note: This wrapper allows easier mocking in tests.
    """
    async def _dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    ) -> Dict[str, Any]:
        return await get_current_user(request, credentials)
    return _dependency
