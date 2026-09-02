from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import uuid4

from jose import JWTError, jwt
from sqlalchemy.orm import joinedload

from app.config import settings
from app.db.database import SessionLocal
from app.models.booking import Booking
from app.models.care import PostVisitFollowup, RecallCampaign
from app.models.patient import Patient
from app.services.reminder_service import _send_sms, _send_whatsapp, _send_telegram, _send_email

logger = logging.getLogger("care_service")


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _channels(raw: str) -> list[str]:
    allowed = {"sms", "whatsapp", "email", "telegram"}
    return [x.strip().lower() for x in str(raw or "").split(",") if x.strip().lower() in allowed]


def _target(patient: Patient, channel: str):
    user = patient.user
    if channel in {"sms", "whatsapp"}: return user.phone if user else None
    if channel == "email": return user.email if user else None
    if channel == "telegram": return patient.reminder_telegram_chat_id
    return None


def _pick_channel(patient: Patient, configured: str):
    preferred = _channels(patient.reminder_channels or configured)
    fallback = _channels(configured)
    for ch in preferred + fallback:
        target = _target(patient, ch)
        if target:
            return ch, target
    return None, None


def _token(purpose: str, row_id: int, token_id: str, ttl_hours: int):
    now = datetime.now(timezone.utc)
    payload = {"sub": str(row_id), "purpose": purpose, "jti": token_id, "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=ttl_hours)).timestamp())}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _resolve(token: str, purpose: str):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Link non valido o scaduto") from exc
    if payload.get("purpose") != purpose:
        raise ValueError("Link non valido")
    return int(payload["sub"]), str(payload.get("jti") or "")


def followup_url(row: PostVisitFollowup):
    token = _token("post_visit_followup", row.id, row.token_id, settings.FOLLOWUP_TOKEN_TTL_HOURS)
    base = settings.CUP_PUBLIC_BASE_URL.rstrip("/")
    path = f"/followup.html?token={quote(token, safe='')}"
    return base + path if base else path


def recall_url(row: RecallCampaign):
    token = _token("recall_action", row.id, row.token_id, settings.RECALL_TOKEN_TTL_HOURS)
    base = settings.CUP_PUBLIC_BASE_URL.rstrip("/")
    path = f"/recall.html?token={quote(token, safe='')}"
    return base + path if base else path


def resolve_followup_token(token: str): return _resolve(token, "post_visit_followup")
def resolve_recall_token(token: str): return _resolve(token, "recall_action")


def ensure_care_for_completed_booking(db, booking: Booking):
    if booking.status != "completed": return
    patient = booking.patient
    if not patient: return
    anchor = booking.end_at or booking.scheduled_at or _utcnow()
    followup_enabled = getattr(booking.visit_type, "followup_enabled", None) if booking.visit_type else None
    if followup_enabled is None: followup_enabled = settings.FOLLOWUP_ENABLED
    if settings.FOLLOWUP_ENABLED and followup_enabled and not db.query(PostVisitFollowup).filter(PostVisitFollowup.booking_id == booking.id).first():
        db.add(PostVisitFollowup(booking_id=booking.id, patient_id=booking.patient_id,
            scheduled_for=anchor + timedelta(hours=settings.FOLLOWUP_DELAY_HOURS), status="scheduled", token_id=uuid4().hex))
    recall_days = getattr(booking.visit_type, "recall_days", None) if booking.visit_type else None
    if recall_days is None: recall_days = settings.RECALL_DEFAULT_DAYS
    recall_enabled = getattr(booking.visit_type, "recall_enabled", None) if booking.visit_type else None
    if recall_enabled is None: recall_enabled = settings.RECALL_ENABLED
    if recall_enabled and int(recall_days or 0) > 0 and not db.query(RecallCampaign).filter(RecallCampaign.source_booking_id == booking.id).first():
        db.add(RecallCampaign(source_booking_id=booking.id, patient_id=booking.patient_id, visit_type_id=booking.visit_type_id,
            due_at=anchor + timedelta(days=int(recall_days)), status="scheduled", token_id=uuid4().hex))
    db.commit()


def backfill_care(db):
    rows = db.query(Booking).options(joinedload(Booking.patient).joinedload(Patient.user), joinedload(Booking.visit_type)).filter(Booking.status == "completed").all()
    for row in rows: ensure_care_for_completed_booking(db, row)


def _send(channel: str, target: str, text: str):
    fn = {"sms": _send_sms, "whatsapp": _send_whatsapp, "telegram": _send_telegram, "email": _send_email}.get(channel)
    return fn(target, text) if fn else (False, "Canale non supportato")


def send_followup(db, row: PostVisitFollowup):
    row = db.query(PostVisitFollowup).options(joinedload(PostVisitFollowup.patient).joinedload(Patient.user), joinedload(PostVisitFollowup.booking)).filter(PostVisitFollowup.id == row.id).first()
    if not row or row.status not in {"scheduled", "failed"}: return row
    ch, target = _pick_channel(row.patient, settings.FOLLOWUP_CHANNELS)
    if not ch:
        row.status = "skipped"; row.provider_response = "Nessun recapito disponibile"; db.commit(); return row
    text = settings.FOLLOWUP_TEMPLATE.format(service=row.booking.service_name, date=row.booking.scheduled_at.strftime("%d/%m/%Y"), followup_url=followup_url(row))
    ok, msg = _send(ch, target, text)
    row.channel = ch; row.target = target; row.attempts += 1; row.provider_response = msg
    if ok: row.status = "sent"; row.sent_at = _utcnow()
    else: row.status = "failed"
    db.commit(); return row


def send_recall(db, row: RecallCampaign):
    row = db.query(RecallCampaign).options(joinedload(RecallCampaign.patient).joinedload(Patient.user), joinedload(RecallCampaign.source_booking)).filter(RecallCampaign.id == row.id).first()
    if not row or row.status not in {"scheduled", "due", "failed"}: return row
    ch, target = _pick_channel(row.patient, settings.RECALL_CHANNELS)
    if not ch:
        row.status = "failed"; row.provider_response = "Nessun recapito disponibile"; db.commit(); return row
    service = row.source_booking.service_name if row.source_booking else "controllo"
    text = settings.RECALL_TEMPLATE.format(service=service, recall_url=recall_url(row))
    ok, msg = _send(ch, target, text)
    row.channel = ch; row.target = target; row.attempts += 1; row.provider_response = msg
    if ok: row.status = "sent"; row.sent_at = _utcnow()
    else: row.status = "failed"
    db.commit(); return row


def detect_rebooked_recalls(db):
    active = db.query(RecallCampaign).filter(RecallCampaign.status.in_(["scheduled", "due", "sent", "snoozed"])).all()
    for r in active:
        q = db.query(Booking).filter(Booking.patient_id == r.patient_id, Booking.id != (r.source_booking_id or 0), Booking.status.in_(["pending", "confirmed", "completed"]))
        if r.visit_type_id: q = q.filter(Booking.visit_type_id == r.visit_type_id)
        b = q.order_by(Booking.scheduled_at.desc()).first()
        if b and b.scheduled_at >= r.created_at:
            r.status = "booked"; r.booked_booking_id = b.id
    db.commit()


async def care_worker():
    while True:
        db = SessionLocal()
        try:
            backfill_care(db)
            detect_rebooked_recalls(db)
            now = _utcnow()
            followups = db.query(PostVisitFollowup).filter(PostVisitFollowup.status.in_(["scheduled","failed"]), PostVisitFollowup.scheduled_for <= now, PostVisitFollowup.attempts < settings.REMINDER_MAX_ATTEMPTS).limit(30).all()
            for row in followups:
                try: send_followup(db, row)
                except Exception as exc: logger.warning("Follow-up %s: %s", row.id, exc)
            recalls = db.query(RecallCampaign).filter(RecallCampaign.status.in_(["scheduled", "due", "snoozed", "failed"]), RecallCampaign.due_at <= now, RecallCampaign.attempts < settings.REMINDER_MAX_ATTEMPTS).limit(30).all()
            for row in recalls:
                if row.status in {"scheduled","snoozed"}: row.status = "due"; db.commit()
                try: send_recall(db, row)
                except Exception as exc: logger.warning("Recall %s: %s", row.id, exc)
        except Exception as exc:
            logger.warning("Care worker: %s", exc)
        finally:
            db.close()
        await asyncio.sleep(max(30, int(settings.CARE_POLL_SECONDS)))
