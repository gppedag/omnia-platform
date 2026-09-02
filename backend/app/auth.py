from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Optional

import bcrypt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.models.user import User

# auto_error=False is essential for the development role bypass: when the dev
# header is present there is intentionally no Bearer token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password vuota")
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("Password troppo lunga per bcrypt")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _dev_user(role: str):
    """Ephemeral user used only while DEV_ROLE_LOGIN_ENABLED=true.

    It deliberately does not depend on PostgreSQL, password hashes or JWTs.
    The object exposes the same attributes used by role/channel guards.
    """
    if role == "admin":
        return SimpleNamespace(
            id=-9001, email="admin@dev.cup", full_name="Admin sviluppo", role="admin",
            phone=None, is_active=True, can_chat=True, can_phone=True,
        )
    if role == "operator":
        return SimpleNamespace(
            id=-9002, email="operatore@dev.cup", full_name="Operatore sviluppo", role="operator",
            phone=None, is_active=True, can_chat=True, can_phone=True,
        )
    return None


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    x_dev_role: Optional[str] = Header(default=None, alias="X-Dev-Role"),
    db: Session = Depends(get_db),
):
    # Development bypass: map the role selected in the UI to a REAL
    # database user. This keeps users.id foreign keys valid for operations
    # such as handoff acceptance and conversation ownership.
    if settings.DEV_ROLE_LOGIN_ENABLED and x_dev_role:
        role = str(x_dev_role).strip().lower()

        demo_email = {
            "admin": "admin@demo.cup",
            "operator": "operatore@demo.cup",
        }.get(role)

        if not demo_email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ruolo sviluppo non valido",
            )

        dev = db.query(User).filter(
            User.email == demo_email,
            User.role == role,
            User.is_active.is_(True),
        ).first()

        if dev is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Account demo {role} non disponibile",
            )

        return dev

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenziali non valide",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
    return user


def require_role(*roles: str):
    def checker(user=Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permessi insufficienti")
        return user
    return checker


def require_operator_channel(channel: str):
    def checker(user=Depends(get_current_user)):
        if user.role == "admin":
            return user
        if user.role != "operator":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permessi insufficienti")
        allowed = bool(user.can_chat) if channel == "chat" else bool(user.can_phone) if channel == "phone" else False
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Operatore non abilitato al canale {channel}")
        return user
    return checker
