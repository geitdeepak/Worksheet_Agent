import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import SchoolClass, User

_ITER = 240_000
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITER)
    return f"pbkdf2_sha256${_ITER}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
    return hmac.compare_digest(dk.hex(), digest)


def create_token(user: User) -> str:
    s = get_settings()
    payload = {"sub": str(user.id), "role": user.role,
               "exp": datetime.now(timezone.utc) + timedelta(hours=s.jwt_ttl_hours)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    try:
        payload = jwt.decode(creds.credentials, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again.")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators can do this.")
    return user


def require_staff(user: User = Depends(current_user)) -> User:
    """Administrators and teachers. Parents only reach their own practice-sheet pages."""
    if user.role not in ("admin", "teacher"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only school staff can do this.")
    return user


def require_parent(user: User = Depends(current_user)) -> User:
    if user.role != "parent":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This page is for parents.")
    return user


def can_access_class(user: User, class_id: int) -> bool:
    return user.role == "admin" or class_id in (user.class_access or [])


def get_class_for(db: Session, user: User, class_id: int) -> SchoolClass:
    """Class-level isolation: teachers only reach classes they are assigned to."""
    c = db.get(SchoolClass, class_id)
    if c is None or not can_access_class(user, class_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found.")
    return c
