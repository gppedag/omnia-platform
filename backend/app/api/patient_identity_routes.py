from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db.database import get_db
from app.models.patient import Patient
from app.services.patient_identity_service import (
    IdentityConflict,
    find_patient_by_fiscal_code,
    find_users_by_phone,
    normalize_email,
    normalize_fiscal_code,
    normalize_phone,
    resolve_patient,
)

router = APIRouter(
    prefix="/api/patient-identity",
    tags=["patient-identity"],
)


class IdentityResolveRequest(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    fiscal_code: str | None = None
    date_of_birth: str | None = None
    source: str = "voice_ai"
    create_if_missing: bool = False


def patient_payload(patient: Patient) -> dict:
    user = patient.user

    return {
        "patient_id": patient.id,
        "user_id": user.id if user else None,
        "full_name": user.full_name if user else None,
        "email": user.email if user else None,
        "phone": user.phone if user else None,
        "fiscal_code": patient.fiscal_code,
        "date_of_birth": (
            patient.date_of_birth.isoformat()
            if patient.date_of_birth
            else None
        ),
        "identity_status": patient.identity_status,
    }


@router.post("/resolve")
def resolve_identity(
    payload: IdentityResolveRequest,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    dob = None

    if payload.date_of_birth:
        try:
            dob = datetime.strptime(
                payload.date_of_birth,
                "%Y-%m-%d",
            ).date()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Data di nascita non valida",
            )

    # --------------------------------------------------------
    # Priorita 1: Codice fiscale
    # --------------------------------------------------------
    cf = normalize_fiscal_code(payload.fiscal_code)

    if cf:
        patient = find_patient_by_fiscal_code(db, cf)

        if patient:
            return {
                "status": "matched",
                "confidence": "strong",
                "match_reason": "fiscal_code",
                "patient": patient_payload(patient),
            }

    # --------------------------------------------------------
    # Priorita 2: telefono, solo se univoco
    # --------------------------------------------------------
    phone = normalize_phone(payload.phone or "")

    if phone:
        users = find_users_by_phone(db, phone)

        if len(users) == 1:
            patient = (
                db.query(Patient)
                .filter(Patient.user_id == users[0].id)
                .first()
            )

            if patient:
                return {
                    "status": "matched",
                    "confidence": "medium",
                    "match_reason": "phone",
                    "patient": patient_payload(patient),
                }

        if len(users) > 1:
            return {
                "status": "ambiguous",
                "reason": "multiple_profiles_for_phone",
            }

    # --------------------------------------------------------
    # Nessuna creazione automatica, salvo richiesta esplicita
    # --------------------------------------------------------
    if not payload.create_if_missing:
        return {
            "status": "not_found",
        }

    try:
        patient = resolve_patient(
            db,
            full_name=(payload.full_name or "Paziente").strip(),
            email=normalize_email(payload.email),
            phone=phone,
            fiscal_code=cf,
            date_of_birth=dob,
            source=payload.source,
            create_if_missing=True,
        )
    except IdentityConflict as exc:
        return {
            "status": "ambiguous",
            "reason": str(exc),
        }

    db.commit()
    db.refresh(patient)

    return {
        "status": "created",
        "confidence": "self_declared",
        "patient": patient_payload(patient),
    }
