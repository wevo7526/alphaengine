"""
Clerk JWT verification for multi-user support.

Hardened auth layer:
- In production (ENV=production), CLERK_ISSUER is REQUIRED. Missing config
  refuses to verify tokens (returns None) so downstream `require_user_id`
  dependencies will 401 on every request.
- In dev (ENV=development), if CLERK_ISSUER is missing, tokens are decoded
  without signature verification for local testing only.
- `get_user_id` returns Optional[str] (for optional auth contexts)
- `require_user_id` raises 401 HTTPException if no valid user
"""

import jwt
from jwt import PyJWKClient
import logging
import time
from fastapi import Request, HTTPException

from config import settings

logger = logging.getLogger(__name__)

# Cache JWKS client (thread-safe, handles key rotation internally)
_jwks_client: PyJWKClient | None = None
_jwks_client_timestamp: float = 0
_JWKS_CLIENT_TTL = 3600  # Recreate client hourly to pick up key rotations

# Production hard-fail: if ENV=production and no CLERK_ISSUER, log a loud
# warning at import time. The backend refuses to authenticate tokens in this
# state — every protected route returns 401 until config is fixed.
if settings.ENV == "production" and not settings.CLERK_ISSUER:
    logger.error(
        "CRITICAL: ENV=production but CLERK_ISSUER is empty. "
        "All authenticated endpoints will return 401. "
        "Set CLERK_ISSUER in Railway environment variables."
    )


def _get_jwks_client() -> PyJWKClient | None:
    """Get or create a cached JWKS client for Clerk token verification."""
    global _jwks_client, _jwks_client_timestamp

    clerk_issuer = settings.CLERK_ISSUER or ""
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
    Returns None if no valid token.

    SECURITY: In production, a missing CLERK_ISSUER means NO token is trusted.
    Every authenticated route will 401. This is intentional — we fail closed.
    """
    if request is None:
        return None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    clerk_issuer = settings.CLERK_ISSUER or ""

    # Production REQUIRES a configured issuer. No unverified fallback.
    if settings.ENV == "production" and not clerk_issuer:
        logger.warning("Production auth attempted but CLERK_ISSUER is unset — refusing token")
        return None

    if not clerk_issuer:
        # Dev only: decode without verification for local testing
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload.get("sub")
        except Exception:
            return None

    jwks_client = _get_jwks_client()
    if not jwks_client:
        logger.warning("JWKS client unavailable — cannot verify token")
        return None

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        audience = settings.CLERK_AUDIENCE or None
        decode_options = {}
        if not audience:
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


def require_user_id(request: Request) -> str:
    """
    Dependency that requires a valid authenticated user.

    Use on every route that accesses user-scoped data. Raises 401 if:
    - No Authorization header
    - Token present but invalid
    - Production + CLERK_ISSUER missing

    Returns the user_id string.
    """
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id
