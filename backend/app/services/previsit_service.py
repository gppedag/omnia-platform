from __future__ import annotations
import json
from datetime import datetime, timedelta
from urllib.parse import quote
from jose import jwt, JWTError
from sqlalchemy.orm import joinedload
from app.config import settings
from app.models.booking import Booking
from app.models.previsit import PreVisitTemplate, PreVisitSubmission, BookingCheckIn

DEFAULT_FORM = [
    {"key":"reason","label":"Motivo della visita","type":"textarea","required":True},
    {"key":"medications","label":"Farmaci assunti regolarmente","type":"textarea","required":False},
    {"key":"allergies","label":"Allergie note","type":"textarea","required":False},
    {"key":"previous_exams","label":"Esami o referti precedenti rilevanti","type":"textarea","required":False},
    {"key":"notes","label":"Altre informazioni utili al medico","type":"textarea","required":False},
]


def ensure_default_templates(db):
    if db.query(PreVisitTemplate).count() > 0:
        return
    from app.models.calendar import VisitType
    visits = db.query(VisitType).filter(VisitType.active == True).all()
    if visits:
        for vt in visits:
            db.add(PreVisitTemplate(name=f"Pre-visita - {vt.name}", visit_type_id=vt.id, form_json=json.dumps(DEFAULT_FORM, ensure_ascii=False)))
    else:
        db.add(PreVisitTemplate(name="Pre-visita standard", form_json=json.dumps(DEFAULT_FORM, ensure_ascii=False)))
    db.commit()


def ensure_previsit_for_booking(db, booking: Booking):
    if not settings.PREVISIT_ENABLED or booking.status in {"cancelled", "completed"}:
        return None
    current = db.query(PreVisitSubmission).filter(PreVisitSubmission.booking_id == booking.id).first()
    if current:
        return current
    template = None
    if booking.visit_type_id:
        template = db.query(PreVisitTemplate).filter(PreVisitTemplate.active == True, PreVisitTemplate.visit_type_id == booking.visit_type_id).first()
    if not template:
        template = db.query(PreVisitTemplate).filter(PreVisitTemplate.active == True, PreVisitTemplate.visit_type_id == None).first()
    if not template:
        template = db.query(PreVisitTemplate).filter(PreVisitTemplate.active == True).first()
    if not template:
        ensure_default_templates(db)
        template = db.query(PreVisitTemplate).filter(PreVisitTemplate.active == True).first()
    if not template:
        return None
    row = PreVisitSubmission(booking_id=booking.id, template_id=template.id, status="pending")
    db.add(row)
    db.flush()
    if not db.query(BookingCheckIn).filter(BookingCheckIn.booking_id == booking.id).first():
        db.add(BookingCheckIn(booking_id=booking.id, status="not_arrived"))
    db.commit(); db.refresh(row)
    return row


def _token(booking_id: int, purpose: str, ttl_hours: int | None = None) -> str:
    ttl = ttl_hours or settings.PREVISIT_TOKEN_TTL_HOURS
    payload = {"sub": str(booking_id), "purpose": purpose, "exp": datetime.utcnow() + timedelta(hours=ttl)}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def resolve_token(token: str, purpose: str) -> int:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Link non valido o scaduto") from exc
    if payload.get("purpose") != purpose:
        raise ValueError("Link non valido")
    return int(payload["sub"])


def previsit_url(booking_id: int) -> str:
    base = settings.CUP_PUBLIC_BASE_URL.rstrip("/")
    path = f"/previsit.html?token={quote(_token(booking_id, 'previsit'), safe='')}"
    return base + path if base else path


def checkin_url(booking_id: int) -> str:
    base = settings.CUP_PUBLIC_BASE_URL.rstrip("/")
    path = f"/checkin.html?token={quote(_token(booking_id, 'checkin'), safe='')}"
    return base + path if base else path


def serialize_submission(row: PreVisitSubmission):
    b = row.booking
    p = getattr(b, "patient", None)
    u = getattr(p, "user", None) if p else None
    return {
        "id": row.id, "booking_id": row.booking_id, "status": row.status,
        "patient_name": getattr(u, "full_name", None), "service_name": getattr(b, "service_name", None),
        "scheduled_at": getattr(b, "scheduled_at", None), "completed_at": row.completed_at,
        "consent_accepted": row.consent_accepted, "template_id": row.template_id,
    }
