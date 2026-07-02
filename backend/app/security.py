"""
security.py — Password hashing and JWT token logic.

Two responsibilities:
1. Password hashing: bcrypt via passlib. Passwords are stored as one-way hashes.
   bcrypt is deliberately slow (cost factor 12) to make brute-force attacks expensive.

2. JWT tokens: signed JSON payloads via python-jose. When a user logs in, we issue
   a token containing their user_id and role. The token is signed with JWT_SECRET_KEY
   using HMAC-SHA256. The server can verify any token's signature without storing sessions.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import database, models

# ── Password hashing ──────────────────────────────────────────────────────────

# CryptContext handles algorithm selection and future migrations.
# schemes=["bcrypt"] means all new hashes use bcrypt.
# deprecated="auto" means if we ever add a new scheme, old hashes are auto-detected.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash a plain-text password. Returns a bcrypt hash string."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored hash. Never exposes the original."""
    return pwd_context.verify(plain, hashed)


# ── JWT tokens ────────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY is not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours


def create_access_token(user_id: int, role: str) -> str:
    """
    Create a signed JWT. The payload contains user_id, role, and an expiry timestamp.
    The signature is produced with HMAC-SHA256 using JWT_SECRET_KEY.
    Anyone can decode the payload (it's base64) but cannot forge the signature.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),   # "subject" — standard JWT claim for the user identifier
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ── Request dependency ────────────────────────────────────────────────────────

# HTTPBearer reads the "Authorization: Bearer <token>" header automatically.
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(database.get_db),
) -> models.User:
    """
    FastAPI dependency. Verifies the JWT in the Authorization header and returns
    the corresponding User row. Raises 401 if the token is missing, expired, or tampered.

    Usage on any protected endpoint:
        @router.get("/protected")
        def my_endpoint(current_user: models.User = Depends(get_current_user)):
            ...
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
    return user
