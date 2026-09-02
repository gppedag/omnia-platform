import secrets
from datetime import date
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models.user import User
from app.models.patient import Patient
from app.services.patient_otp_service import normalize_phone


class IdentityConflict(Exception):
    pass


def normalize_fiscal_code(value: str | None) -> str:
    return "".join(str(value or "").upper().split())


def normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def find_patient_by_fiscal_code(
    db: Session,
    fiscal_code: str | None,
) -> Optional[Patient]:
    cf = normalize_fiscal_code(fiscal_code)

    if not cf:
        return None

    return (
        db.query(Patient)
        .filter(
            func.upper(func.trim(Patient.fiscal_code)) == cf
        )
        .first()
    )


def find_user_by_email(
    db: Session,
    email: str | None,
) -> Optional[User]:
    email = normalize_email(email)

    if not email:
        return None

    return (
        db.query(User)
        .filter(func.lower(User.email) == email)
        .first()
    )


def find_users_by_phone(
    db: Session,
    phone: str | None,
) -> list[User]:
    phone = normalize_phone(phone or "")

    if not phone:
        return []

    users = (
        db.query(User)
        .filter(
            User.role == "patient",
            User.is_active.is_(True),
        )
        .all()
    )

    return [
        user
        for user in users
        if normalize_phone(user.phone or "") == phone
    ]


def ensure_patient_profile(
    db: Session,
    user: User,
    *,
    identity_status: str = "self_declared",
    fiscal_code: str | None = None,
    date_of_birth: date | None = None,
    notes: str | None = None,
) -> Patient:

    patient = (
        db.query(Patient)
        .filter(Patient.user_id == user.id)
        .first()
    )

    if patient:
        return patient

    patient = Patient(
        user_id=user.id,
        fiscal_code=normalize_fiscal_code(fiscal_code) or None,
        date_of_birth=date_of_birth,
        identity_status=identity_status,
        notes=notes,
    )

    db.add(patient)
    db.flush()

    return patient


def resolve_patient(
    db: Session,
    *,
    full_name: str,
    email: str | None = None,
    phone: str | None = None,
    fiscal_code: str | None = None,
    date_of_birth: date | None = None,
    source: str = "web",
    create_if_missing: bool = True,
) -> Patient:

    email = normalize_email(email)
    phone = normalize_phone(phone or "")
    fiscal_code = normalize_fiscal_code(fiscal_code)

    # 1. Il CF e la chiave primaria di riconciliazione anagrafica.
    if fiscal_code:
        patient = find_patient_by_fiscal_code(db, fiscal_code)

        if patient:
            user = patient.user

            if user is None:
                raise IdentityConflict(
                    "Anagrafica paziente presente ma priva di account digitale."
                )

            if phone:
                existing_phone = normalize_phone(user.phone or "")

                if existing_phone and existing_phone != phone:
                    raise IdentityConflict(
                        "Telefono non coerente con l'anagrafica esistente."
                    )

                if not existing_phone:
                    user.phone = phone

            if email:
                owner = find_user_by_email(db, email)

                if owner and owner.id != user.id:
                    raise IdentityConflict(
                        "Email gia associata a un altro account."
                    )

                if not user.email:
                    user.email = email

            return patient

    # 2. Account gia noto tramite e-mail.
    if email:
        user = find_user_by_email(db, email)

        if user:
            if user.role != "patient":
                raise IdentityConflict(
                    "L'email appartiene a un account non paziente."
                )

            return ensure_patient_profile(
                db,
                user,
                fiscal_code=fiscal_code,
                date_of_birth=date_of_birth,
            )

    # 3. Telefono: lo usiamo solo se identifica un singolo account.
    if phone:
        phone_users = find_users_by_phone(db, phone)

        if len(phone_users) == 1:
            return ensure_patient_profile(
                db,
                phone_users[0],
                fiscal_code=fiscal_code,
                date_of_birth=date_of_birth,
            )

        if len(phone_users) > 1:
            raise IdentityConflict(
                "Il numero e associato a piu profili. Verifica identita necessaria."
            )

    if not create_if_missing:
        raise IdentityConflict("Paziente non trovato.")

    # 4. Nuova identita self-service.
    if not email:
        # users.email e attualmente NOT NULL.
        # Generiamo quindi un identificativo tecnico non utilizzabile come login.
        email = f"patient-{secrets.token_hex(12)}@internal.demo"

    user = User(
        email=email,
        hashed_password=hash_password(secrets.token_urlsafe(24)),
        full_name=full_name.strip(),
        role="patient",
        phone=phone or None,
        phone_verified=False,
        email_verified=False,
        account_status="active",
        activation_source=source,
        is_active=True,
        can_chat=True,
        can_phone=True,
    )

    db.add(user)
    db.flush()

    patient = Patient(
        user_id=user.id,
        fiscal_code=fiscal_code or None,
        date_of_birth=date_of_birth,
        identity_status="self_declared",
        notes=f"Identita creata da {source}",
    )

    db.add(patient)
    db.flush()

    return patient
