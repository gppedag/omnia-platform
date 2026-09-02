from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models.user import User

DEMO_STAFF = (
    ("admin@demo.cup", "Admin Demo CUP", "admin", "AdminDemo123!", True, True),
    ("operatore@demo.cup", "Operatore Demo CUP", "operator", "OperatorDemo123!", True, True),
)


def _spec_for(email: str):
    key = (email or "").strip().lower()
    for spec in DEMO_STAFF:
        if spec[0] == key:
            return spec
    return None


def ensure_demo_account(db: Session, email: str, reset_password: bool = True) -> User | None:
    """Crea/riallinea un singolo account demo.

    Usata anche dal login, quindi gli account di collaudo non dipendono dal
    seed completo, dalla sequenza di startup o da un database proveniente da
    release precedenti.
    """
    spec = _spec_for(email)
    if spec is None:
        return None
    email, full_name, role, password, can_chat, can_phone = spec
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(
            email=email,
            full_name=full_name,
            role=role,
            hashed_password=hash_password(password),
            is_active=True,
            can_chat=can_chat,
            can_phone=can_phone,
        )
        db.add(user)
    else:
        user.full_name = full_name
        user.role = role
        user.is_active = True
        user.can_chat = can_chat
        user.can_phone = can_phone
        if reset_password:
            user.hashed_password = hash_password(password)
    db.commit()
    db.refresh(user)
    return user


def ensure_demo_staff(db: Session) -> dict:
    created = 0
    reset = 0
    for spec in DEMO_STAFF:
        email = spec[0]
        existed = db.query(User).filter(User.email == email).first() is not None
        ensure_demo_account(db, email, reset_password=False)
        if existed:
            reset += 1
        else:
            created += 1
    return {"created": created, "reset": reset, "accounts": [x[0] for x in DEMO_STAFF]}
