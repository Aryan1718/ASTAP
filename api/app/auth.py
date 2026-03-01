import json
import logging
import time
from dataclasses import dataclass
from threading import Lock
from urllib.error import URLError
from urllib.request import urlopen

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.config import settings

logger = logging.getLogger(__name__)
_bearer_scheme = HTTPBearer(auto_error=False)
_jwks_lock = Lock()
_jwks_cache: dict[str, object] = {"expires_at": 0.0, "keys": {}}
_JWKS_TTL_SECONDS = 600


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str | None = None


def _jwks_url() -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


def _issuer() -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1"


def _fetch_jwks() -> dict[str, dict]:
    try:
        with urlopen(_jwks_url(), timeout=5) as response:
            payload = json.load(response)
    except (OSError, TimeoutError, URLError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Unable to fetch auth keys") from exc

    keys = {
        key["kid"]: key
        for key in payload.get("keys", [])
        if isinstance(key, dict) and key.get("kid")
    }
    if not keys:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth key set is empty")
    return keys


def _get_jwks(force_refresh: bool = False) -> dict[str, dict]:
    now = time.monotonic()
    with _jwks_lock:
        expires_at = float(_jwks_cache["expires_at"])
        cached_keys = _jwks_cache["keys"]
        if not force_refresh and cached_keys and now < expires_at:
            return cached_keys  # type: ignore[return-value]

        keys = _fetch_jwks()
        _jwks_cache["keys"] = keys
        _jwks_cache["expires_at"] = now + _JWKS_TTL_SECONDS
        return keys


def _get_signing_key(token: str):
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token header") from exc

    kid = header.get("kid")
    alg = header.get("alg")
    if not kid or not alg:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token header")

    keys = _get_jwks()
    jwk = keys.get(kid)
    if jwk is None:
        keys = _get_jwks(force_refresh=True)
        jwk = keys.get(kid)
    if jwk is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown token key")

    try:
        signing_key = jwt.PyJWK.from_dict(jwk).key
    except (jwt.PyJWTError, ValueError) as exc:
        logger.warning(
            "Failed to parse Supabase JWK",
            extra={
                "supabase_url": settings.supabase_url,
                "jwt_kid": kid,
                "jwt_alg": alg,
                "jwk_kty": jwk.get("kty"),
                "jwk_use": jwk.get("use"),
            },
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to verify token with Supabase JWKS. Check that SUPABASE_URL matches the client project and sign in again.",
        ) from exc

    return signing_key, alg


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    signing_key, algorithm = _get_signing_key(credentials.credentials)
    try:
        payload = jwt.decode(
            credentials.credentials,
            key=signing_key,
            algorithms=[algorithm],
            audience=settings.supabase_jwt_audience,
            issuer=_issuer(),
            options={"require": ["sub", "exp", "iss", "aud"]},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        logger.warning(
            "Supabase token validation failed",
            extra={
                "supabase_url": settings.supabase_url,
                "jwt_alg": algorithm,
            },
            exc_info=exc,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")

    email = payload.get("email")
    return CurrentUser(user_id=user_id, email=email if isinstance(email, str) else None)
