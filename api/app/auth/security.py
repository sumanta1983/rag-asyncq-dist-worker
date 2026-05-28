from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from ..config import settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(*, user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Raises jwt.InvalidTokenError on bad/expired token."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


MOBILE_REGEX = r"^[6-9]\d{9}$"  # Indian mobile: 10 digits, starts 6-9


def normalize_mobile(raw: str) -> str:
    """Strip whitespace, '+91', leading zeros. Return canonical +91XXXXXXXXXX."""
    s = raw.strip().replace(" ", "").replace("-", "")
    if s.startswith("+91"):
        s = s[3:]
    elif s.startswith("91") and len(s) == 12:
        s = s[2:]
    s = s.lstrip("0")
    return "+91" + s
