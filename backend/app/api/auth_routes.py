import secrets
from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel
from typing import Literal
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from app.db.database import get_db
from app.models.user import User
from app.models.patient import Patient
from app.schemas import UserCreate, UserLogin, UserOut, Token
from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    db: Session = Depends(get_db),
    x_admin_bootstrap_token: str | None = Header(default=None),
):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email già registrata")

    # La registrazione pubblica può creare soltanto pazienti.
    # Admin/operator richiedono il bootstrap token configurato lato server.
    if payload.role in {"admin", "operator"}:
        if not settings.ADMIN_BOOTSTRAP_TOKEN or x_admin_bootstrap_token != settings.ADMIN_BOOTSTRAP_TOKEN:
            raise HTTPException(status_code=403, detail="Bootstrap token amministrativo richiesto")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        phone=payload.phone,
        can_chat=True,
        can_phone=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class DevRoleLogin(BaseModel):
    role: Literal["admin", "operator"]


# OMNIA_SECURE_DEV_LOGIN_V1
@router.post("/dev-login", response_model=Token)
def dev_role_login(
    payload: DevRoleLogin,
    db: Session = Depends(get_db),
    x_cup_service_secret: str | None = Header(
        default=None,
        alias="X-CUP-Service-Secret",
    ),
):
    """Accesso semplificato per sviluppo.

    Non richiede password: la selezione del ruolo crea/riallinea l'account demo
    corrispondente e restituisce un JWT normale. Tutte le API continuano quindi
    a verificare ruolo e abilitazioni canale come in produzione.
    """
    if not settings.DEV_ROLE_LOGIN_ENABLED:
        raise HTTPException(
            status_code=404,
            detail="Accesso sviluppo non abilitato"
        )

    expected = os.getenv(
        "DEV_LOGIN_SERVICE_SECRET",
        ""
    )

    if (
        not expected
        or not x_cup_service_secret
        or not secrets.compare_digest(
            expected,
            x_cup_service_secret,
        )
    ):
        raise HTTPException(
            status_code=403,
            detail="Accesso di servizio non autorizzato"
        )

    from app.services.demo_staff import ensure_demo_account

    email = "admin@demo.cup" if payload.role == "admin" else "operatore@demo.cup"
    user = ensure_demo_account(db, email, reset_password=False)
    if user is None:
        raise HTTPException(status_code=500, detail="Impossibile inizializzare il profilo di sviluppo")
    if not user.is_active:
        user.is_active = True
        db.commit()
        db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": user.role, "dev_login": True})
    return Token(access_token=token)


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    email = str(payload.email).strip().lower()

    # Gli account demo vengono garantiti anche al momento del login.
    # Non dipendono quindi dal seed completo o dall'ordine di startup.
    if settings.DEMO_LOGIN_USERS_ENABLED and email in {"admin@demo.cup", "operatore@demo.cup"}:
        from app.services.demo_staff import ensure_demo_account
        ensure_demo_account(db, email, reset_password=False)

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email o password errati")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Utente disabilitato")
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return Token(access_token=token)


@router.get("/demo-status")
def demo_status(db: Session = Depends(get_db)):
    accounts = []
    for email in ("admin@demo.cup", "operatore@demo.cup"):
        user = db.query(User).filter(User.email == email).first()
        accounts.append({
            "email": email,
            "exists": bool(user),
            "active": bool(user.is_active) if user else False,
            "role": user.role if user else None,
        })
    return {"enabled": bool(settings.DEMO_LOGIN_USERS_ENABLED), "accounts": accounts}


@router.get("/me", response_model=UserOut)
def me(user=Depends(get_current_user)):
    return user


# ============================================================
# Patient passwordless authentication
# ============================================================

from fastapi import Request
from datetime import datetime, timedelta
from app.services.patient_otp_service import (
    create_challenge,
    verify_challenge,
    normalize_phone,
)
from app.services.patient_identity_service import find_users_by_phone


class PatientOtpStart(BaseModel):
    phone: str


class PatientOtpVerify(BaseModel):
    phone: str
    challenge_id: int
    code: str


@router.post("/patient/start")
def patient_otp_start(
    payload: PatientOtpStart,
    request: Request,
    db: Session = Depends(get_db),
):
    phone = normalize_phone(payload.phone)

    users = find_users_by_phone(db, phone)

    purpose = "login" if users else "registration"

    try:
        challenge = create_challenge(
            db,
            phone=phone,
            purpose=purpose,
            request_ip=request.client.host if request.client else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    response = {
        "challenge_id": challenge["challenge_id"],
        "expires_in": challenge["expires_in"],
        "known_account": bool(users),
    }

    # SOLO POC / DEMO.
    # Da disabilitare quando colleghiamo SMS/WhatsApp reali.
    if getattr(settings, "OTP_DEMO_MODE", False):
        response["demo_code"] = challenge["code"]

    return response


@router.post("/patient/verify")
def patient_otp_verify(
    payload: PatientOtpVerify,
    db: Session = Depends(get_db),
):
    phone = normalize_phone(payload.phone)

    ok = verify_challenge(
        db,
        challenge_id=payload.challenge_id,
        phone=phone,
        code=payload.code,
    )

    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Codice non valido o scaduto",
        )

    users = find_users_by_phone(db, phone)

    if len(users) == 1:
        user = users[0]

        if user.account_status == "suspended":
            raise HTTPException(
                status_code=403,
                detail="Account sospeso",
            )

        user.phone_verified = True
        user.account_status = "active"
        user.last_login_at = datetime.utcnow()

        db.commit()
        db.refresh(user)

        token = create_access_token(
            {
                "sub": str(user.id),
                "role": user.role,
                "auth_method": "otp",
            }
        )

        return {
            "status": "authenticated",
            "access_token": token,
            "token_type": "bearer",
            "needs_registration": False,
        }

    if len(users) > 1:
        return {
            "status": "identity_required",
            "needs_registration": False,
            "multiple_profiles": True,
        }

    registration_token = create_access_token(
        {
            "phone": phone,
            "purpose": "patient_registration",
            "auth_method": "otp",
        },
        expires_delta=timedelta(minutes=10),
    )

    return {
        "status": "registration_required",
        "needs_registration": True,
        "verified_phone": phone,
        "registration_token": registration_token,
        "registration_token_expires_in": 600,
    }


# ============================================================
# Patient registration after verified OTP
# ============================================================

class PatientRegistrationComplete(BaseModel):
    registration_token: str
    first_name: str
    last_name: str
    email: str
    fiscal_code: str
    date_of_birth: str


def _normalize_fiscal_code(value: str) -> str:
    return "".join(str(value or "").upper().split())


@router.post("/patient/complete-registration")
def patient_complete_registration(
    payload: PatientRegistrationComplete,
    db: Session = Depends(get_db),
):
    # --------------------------------------------------------
    # 1. Verify short-lived registration token
    # --------------------------------------------------------
    try:
        token_data = jwt.decode(
            payload.registration_token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Sessione di registrazione non valida o scaduta",
        )

    if token_data.get("purpose") != "patient_registration":
        raise HTTPException(
            status_code=401,
            detail="Token non valido per la registrazione",
        )

    phone = normalize_phone(token_data.get("phone") or "")

    if not phone:
        raise HTTPException(
            status_code=400,
            detail="Numero di telefono non valido",
        )

    # --------------------------------------------------------
    # 2. Normalize submitted identity data
    # --------------------------------------------------------
    first_name = payload.first_name.strip()
    last_name = payload.last_name.strip()
    full_name = f"{first_name} {last_name}".strip()
    email = payload.email.strip().lower()
    fiscal_code = _normalize_fiscal_code(payload.fiscal_code)

    if not first_name or not last_name:
        raise HTTPException(
            status_code=400,
            detail="Nome e cognome obbligatori",
        )

    if "@" not in email:
        raise HTTPException(
            status_code=400,
            detail="Email non valida",
        )

    if len(fiscal_code) < 11:
        raise HTTPException(
            status_code=400,
            detail="Codice fiscale non valido",
        )

    try:
        date_of_birth = datetime.strptime(
            payload.date_of_birth,
            "%Y-%m-%d",
        ).date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Data di nascita non valida",
        )

    # --------------------------------------------------------
    # 3. Phone must not already belong to another patient
    # --------------------------------------------------------
    phone_user = (
        db.query(User)
        .filter(
            User.phone == phone,
            User.role == "patient",
        )
        .first()
    )

    if phone_user:
        raise HTTPException(
            status_code=409,
            detail="Esiste gia un account associato a questo numero",
        )

    # --------------------------------------------------------
    # 4. Look for an existing patient created by reception
    # --------------------------------------------------------
    existing_patient = (
        db.query(Patient)
        .filter(
            Patient.fiscal_code.isnot(None),
        )
        .all()
    )

    existing_patient = next(
        (
            patient
            for patient in existing_patient
            if _normalize_fiscal_code(patient.fiscal_code) == fiscal_code
        ),
        None,
    )

    # --------------------------------------------------------
    # 5A. Existing patient: reconcile digital identity
    # --------------------------------------------------------
    if existing_patient:
        user = existing_patient.user

        if not user:
            raise HTTPException(
                status_code=409,
                detail="Anagrafica esistente da verificare in reception",
            )

        # Do not silently replace another person's phone.
        if user.phone and normalize_phone(user.phone) != phone:
            return {
                "status": "reception_verification_required",
                "needs_reception": True,
                "message": (
                    "L'anagrafica risulta gia presente. "
                    "Per sicurezza e necessaria una verifica con la reception."
                ),
            }

        # Date of birth is an additional reconciliation factor.
        if (
            existing_patient.date_of_birth
            and existing_patient.date_of_birth != date_of_birth
        ):
            return {
                "status": "reception_verification_required",
                "needs_reception": True,
                "message": (
                    "I dati inseriti non coincidono completamente "
                    "con l'anagrafica esistente."
                ),
            }

        # Avoid stealing an email already owned by another user.
        email_owner = (
            db.query(User)
            .filter(
                User.email == email,
                User.id != user.id,
            )
            .first()
        )

        if email_owner:
            raise HTTPException(
                status_code=409,
                detail="Email gia associata a un altro account",
            )

        user.phone = phone
        user.phone_verified = True
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.full_name = full_name
        user.account_status = "active"
        user.activation_source = "web"
        user.is_active = True
        user.last_login_at = datetime.utcnow()

        existing_patient.identity_status = "reception_verified"

        db.commit()
        db.refresh(user)

        token = create_access_token(
            {
                "sub": str(user.id),
                "role": "patient",
                "auth_method": "otp",
            }
        )

        return {
            "status": "activated_existing_patient",
            "access_token": token,
            "token_type": "bearer",
            "patient_id": existing_patient.id,
            "identity_status": existing_patient.identity_status,
        }

    # --------------------------------------------------------
    # 5B. New patient
    # --------------------------------------------------------
    email_owner = (
        db.query(User)
        .filter(User.email == email)
        .first()
    )

    if email_owner:
        raise HTTPException(
            status_code=409,
            detail="Email gia registrata",
        )

    user = User(
        email=email,
        hashed_password=hash_password(secrets.token_urlsafe(24)),
        first_name=first_name,
        last_name=last_name,
        full_name=full_name,
        role="patient",
        phone=phone,
        phone_verified=True,
        email_verified=False,
        account_status="active",
        activation_source="web",
        is_active=True,
        can_chat=True,
        can_phone=True,
        last_login_at=datetime.utcnow(),
    )

    db.add(user)
    db.flush()

    patient = Patient(
        user_id=user.id,
        fiscal_code=fiscal_code,
        date_of_birth=date_of_birth,
        identity_status="self_declared",
        notes="Registrazione autonoma con telefono verificato OTP",
    )

    db.add(patient)
    db.commit()
    db.refresh(user)
    db.refresh(patient)

    token = create_access_token(
        {
            "sub": str(user.id),
            "role": "patient",
            "auth_method": "otp",
        }
    )

    return {
        "status": "registered",
        "access_token": token,
        "token_type": "bearer",
        "patient_id": patient.id,
        "identity_status": patient.identity_status,
    }
