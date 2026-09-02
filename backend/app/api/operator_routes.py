from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_role, hash_password
from app.db.database import get_db
from app.models.user import User
from app.services.voip_credentials import (
    encrypt_voip_password,
    decrypt_voip_password,
)

router = APIRouter(
    prefix="/api/operators",
    tags=["operators"]
)


class OperatorCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    phone: str | None = None
    can_chat: bool = True
    can_phone: bool = True

    voip_extension: str | None = None
    voip_password: str | None = None


class OperatorChannels(BaseModel):
    can_chat: bool
    can_phone: bool
    is_active: bool | None = None

    voip_extension: str | None = None
    voip_password: str | None = None


def out(u: User):
    return {
        "id": u.id,
        "full_name": u.full_name,
        "email": u.email,
        "phone": u.phone,
        "role": u.role,
        "can_chat": bool(u.can_chat),
        "can_phone": bool(u.can_phone),
        "is_active": bool(u.is_active),

        "voip_extension":
            u.voip_extension,

        # Mai restituire la password in elenco admin.
        "voip_configured":
            bool(
                u.voip_extension
                and u.voip_password_enc
            ),
    }


@router.get("/me/voip")
def my_voip_credentials(
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    row = (
        db.query(User)
        .filter(
            User.id == user.id,
            User.is_active.is_(True),
        )
        .first()
    )

    if not row:
        raise HTTPException(
            404,
            "Operatore non trovato"
        )

    if not row.can_phone:
        raise HTTPException(
            403,
            "Canale telefonico non abilitato"
        )

    if (
        not row.voip_extension
        or not row.voip_password_enc
    ):
        raise HTTPException(
            404,
            "Credenziali VoIP non configurate"
        )

    return {
        "extension": row.voip_extension,
        "password":
            decrypt_voip_password(
                row.voip_password_enc
            ),
        "domain":
            "pbx.ai.basidiai.it",
        "wss":
            "wss://wss-pbx.ai.basidiai.it/asterisk/ws",
    }



@router.get("/me/voip/status")
async def my_voip_status(
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    from app.services.asterisk_gateway import (
        get_extension_status,
    )

    row = db.get(User, user.id)

    if not row:
        raise HTTPException(
            404,
            "Operatore non trovato"
        )

    if not row.voip_extension:
        return {
            "extension": None,
            "registered": False,
            "in_call": False,
            "status": "not_configured",
            "status_text": "Non configurato",
            "asterisk_status": None,
        }

    return await get_extension_status(
        row.voip_extension
    )



@router.get("")
def list_operators(
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    rows = (
        db.query(User)
        .filter(User.role == "operator")
        .order_by(User.full_name)
        .all()
    )

    return [out(u) for u in rows]


@router.post("", status_code=201)
def create_operator(
    payload: OperatorCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    if (
        db.query(User)
        .filter(User.email == payload.email)
        .first()
    ):
        raise HTTPException(
            400,
            "Email già registrata"
        )

    if len(payload.password) < 8:
        raise HTTPException(
            400,
            "Password temporanea: almeno 8 caratteri"
        )

    extension = (
        payload.voip_extension.strip()
        if payload.voip_extension
        else None
    )

    if extension and not payload.voip_password:
        raise HTTPException(
            400,
            "Inserisci la password SIP dell'interno VoIP"
        )

    row = User(
        email=str(payload.email).lower(),
        full_name=payload.full_name,
        phone=payload.phone,
        role="operator",
        hashed_password=hash_password(
            payload.password
        ),
        can_chat=payload.can_chat,
        can_phone=payload.can_phone,
        is_active=True,

        voip_extension=extension,

        voip_password_enc=(
            encrypt_voip_password(
                payload.voip_password
            )
            if payload.voip_password
            else None
        ),
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return out(row)


@router.patch("/{operator_id}")
def update_operator(
    operator_id: int,
    payload: OperatorChannels,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    row = (
        db.query(User)
        .filter(
            User.id == operator_id,
            User.role == "operator"
        )
        .first()
    )

    if not row:
        raise HTTPException(
            404,
            "Operatore non trovato"
        )

    row.can_chat = payload.can_chat
    row.can_phone = payload.can_phone

    if payload.is_active is not None:
        row.is_active = payload.is_active

    if payload.voip_extension is not None:
        extension = (
            payload.voip_extension.strip()
            or None
        )

        row.voip_extension = extension

        if not extension:
            row.voip_password_enc = None

    # Password vuota = mantieni quella attuale.
    if payload.voip_password:
        row.voip_password_enc = (
            encrypt_voip_password(
                payload.voip_password
            )
        )

    db.commit()
    db.refresh(row)

    return out(row)
