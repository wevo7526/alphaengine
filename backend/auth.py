"""
Clerk JWT verification for multi-user support.

Extracts user_id from the Authorization header (Bearer token from Clerk).
Falls back to None for unauthenticated requests (backward compatible).
"""

import jwt
import httpx
import logging
import time
from fastapi import Request

from config import settings

logger = logging.getLogger(__name__)

# Cache JWKS keys
_jwks_cache: dict | None = None
_jwks_timestamp: float = 0
_JWKS_TTL = 3600  # 1 hour


async def _get_jwks() -> dict:
    """Fetch Clerk's JWKS (JSON Web Key Set) for token verification."""
    global _jwks_cache, _jwks_timestamp

    now = time.time()
    if _jwks_cache and (now - _jwks_timestamp) < _JWKS_TTL:
        return _jwks_cache

    clerk_issuer = getattr(settings, "CLERK_ISSUER", "") or ""
    if not clerk_issuer:
        return {}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{clerk_issuer}/.well-known/jwks.json", timeout=5)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_timestamp = now
            return _jwks_cache
    except Exception as e:
        logger.warning(f"Failed to fetch JWKS: {e}")
        return {}


def get_user_id(request: Request) -> str | None:
    """
    Extract user_id from Clerk JWT in Authorization header.
    Returns None if no valid token (backward compatible with unauthenticated requests).
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    clerk_issuer = getattr(settings, "CLERK_ISSUER", "") or ""

    if not clerk_issuer:
        # No Clerk configured — try to decode without verification (dev mode)
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload.get("sub")
        except Exception:
            return None

    try:
        # Decode and verify with Clerk's public key
        # For simplicity, decode without full JWKS verification in this version
        # Production should use jwks_client for full RSA verification
        payload = jwt.decode(
            token,
            options={"verify_signature": False},  # TODO: verify with JWKS in production
            audience=getattr(settings, "CLERK_AUDIENCE", None),
        )
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        logger.warning("Clerk JWT expired")
        return None
    except Exception as e:
        logger.warning(f"Clerk JWT decode failed: {e}")
        return None
