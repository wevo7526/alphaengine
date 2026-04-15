"""
Clerk JWT verification for multi-user support.

Extracts user_id from the Authorization header (Bearer token from Clerk).
Falls back to None for unauthenticated requests (backward compatible).
"""

import jwt
from jwt import PyJWKClient
import httpx
import logging
import time
from fastapi import Request

from config import settings

logger = logging.getLogger(__name__)

# Cache JWKS client (thread-safe, handles key rotation internally)
_jwks_client: PyJWKClient | None = None
_jwks_client_timestamp: float = 0
_JWKS_CLIENT_TTL = 3600  # Recreate client hourly to pick up key rotations


def _get_jwks_client() -> PyJWKClient | None:
    """Get or create a cached JWKS client for Clerk token verification."""
    global _jwks_client, _jwks_client_timestamp

    clerk_issuer = getattr(settings, "CLERK_ISSUER", "") or ""
    if not clerk_issuer:
        return None

    now = time.time()
    if _jwks_client and (now - _jwks_client_timestamp) < _JWKS_CLIENT_TTL:
        return _jwks_client

    try:
        _jwks_client = PyJWKClient(
            f"{clerk_issuer}/.well-known/jwks.json",
            cache_keys=True,
            lifespan=3600,
        )
        _jwks_client_timestamp = now
        return _jwks_client
    except Exception as e:
        logger.warning(f"Failed to create JWKS client: {e}")
        return None


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
        # No Clerk configured — decode without verification (dev mode only)
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload.get("sub")
        except Exception:
            return None

    # Production: verify signature with Clerk's JWKS
    jwks_client = _get_jwks_client()
    if not jwks_client:
        logger.warning("JWKS client unavailable — cannot verify token")
        return None

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        audience = settings.CLERK_AUDIENCE or None
        decode_options = {}
        if not audience:
            # If no audience configured, skip audience verification
            decode_options["verify_aud"] = False

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=clerk_issuer,
            audience=audience,
            options=decode_options,
        )
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        logger.warning("Clerk JWT expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Clerk JWT verification failed: {e}")
        return None
    except Exception as e:
        logger.warning(f"Clerk JWT decode error: {e}")
        return None
