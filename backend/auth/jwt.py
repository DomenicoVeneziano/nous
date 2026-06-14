# backend/auth/jwt.py
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from config import settings

ALGORITHM = "HS256"


def create_jwt(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def verify_jwt(token: str) -> dict:
    """Verify and decode a JWT token. Raises JWTError on failure."""
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    if "sub" not in payload or "role" not in payload:
        raise JWTError("Invalid token payload")
    return payload
