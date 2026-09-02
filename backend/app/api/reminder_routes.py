from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user, require_role
from app.db.database import get_db
from app.models.booking import Booking
from app.models.patient import Patient
from app.models.reminder import AppointmentReminder, BookingReminderResponse
from app.services.external_calendar import delete_event
from app.services.waitlist_service import create_offer_for_cancelled_booking
from app.services.reminder_service import (
    resolve_action_token,
    ensure_booking_reminders,
    send_row,
    cancel_future_reminders,
    rebuild_future_reminders,
    _channels,
    channel_configured,
)

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


class ReminderAction(BaseModel):
    token: str
    action: str


class ManualReminder(BaseModel):
    channels: Optional[list[str]] = None


def row_dict(r: AppointmentReminder):
    return {
        "id": r.id, "booking_id": r.booking_id, "kind": r.kind, "offset_hours": r.offset_hours,
        "channel": r.channel, "target": r.target, "scheduled_for": r.scheduled_for,
        "status": r.status, "attempts": r.attempts, "sent_at": r.sent_at,
        "message": r.message, "provider_response": r.provider_response,
    }



@router.get("")
def list_reminders(status: Optional[str] = None, limit: int = 200, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(AppointmentReminder).options(joinedload(AppointmentReminder.booking))
    if status:
        q = q.filter(AppointmentReminder.status == status)
    rows = q.order_by(AppointmentReminder.scheduled_for.desc()).limit(min(max(limit, 1), 500)).all()
    return [dict(row_dict(r), service_name=(r.booking.service_name if r.booking else None), scheduled_at=(r.booking.scheduled_at if r.booking else None)) for r in rows]

@router.post("/{reminder_id}/retry")
def retry_reminder(reminder_id: int, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    row = db.get(AppointmentReminder, reminder_id)
    if not row:
        raise HTTPException(404, "Promemoria non trovato")
    row.status = "pending"
    row.scheduled_for = datetime.now()
    db.commit()
    send_row(db, row)
    return row_dict(row)

@router.get("/booking/{booking_id}")
def booking_reminders(booking_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(AppointmentReminder).filter(AppointmentReminder.booking_id == booking_id).order_by(AppointmentReminder.scheduled_for).all()
    responses = db.query(BookingReminderResponse).filter(BookingReminderResponse.booking_id == booking_id).order_by(BookingReminderResponse.created_at.desc()).all()
    return {"items": [row_dict(x) for x in rows], "responses": [{"action": x.action, "created_at": x.created_at} for x in responses]}


@router.post("/booking/{booking_id}/schedule")
def schedule_booking(booking_id: int, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    booking = db.query(Booking).options(joinedload(Booking.patient).joinedload(Patient.user), joinedload(Booking.doctors)).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(404, "Prenotazione non trovata")
    ensure_booking_reminders(db, booking, include_confirmation=False)
    rows = db.query(AppointmentReminder).filter(AppointmentReminder.booking_id == booking_id).order_by(AppointmentReminder.scheduled_for).all()
    return {"ok": True, "items": [row_dict(x) for x in rows]}


@router.post("/booking/{booking_id}/send-now")
def send_now(booking_id: int, payload: ManualReminder, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    booking = db.query(Booking).options(joinedload(Booking.patient).joinedload(Patient.user), joinedload(Booking.doctors)).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(404, "Prenotazione non trovata")
    patient = booking.patient
    if payload.channels:
        channels = [
            str(x).strip().lower()
            for x in payload.channels
            if channel_configured(x)
        ]
    else:
        channels = _channels(patient)

    if not channels:
        raise HTTPException(
            400,
            "Nessun canale promemoria configurato e disponibile"
        )
    from app.services.reminder_service import _target, render_message
    results = []
    for channel in channels:
        target = _target(patient, channel)
        row = AppointmentReminder(booking_id=booking.id, kind="manual", offset_hours=0, channel=channel,
                                  target=target, scheduled_for=datetime.now(), status="pending" if target else "skipped",
                                  message=render_message(booking, "reminder"))
        db.add(row)
        try:
            db.commit(); db.refresh(row)
        except Exception:
            db.rollback()
            # Manuali multipli: evita collisione unique riusando il record esistente.
            row = db.query(AppointmentReminder).filter_by(booking_id=booking.id, kind="manual", offset_hours=0, channel=channel).first()
            if row:
                row.status="pending"; row.target=target; row.scheduled_for=datetime.now(); db.commit()
        if row and row.status == "pending":
            send_row(db, row)
        results.append(row_dict(row))
    return {"ok": True, "items": results}


@router.get("/public/booking")
def public_booking(token: str, db: Session = Depends(get_db)):
    try:
        booking_id = resolve_action_token(token)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    b = db.query(Booking).options(joinedload(Booking.patient).joinedload(Patient.user), joinedload(Booking.doctors), joinedload(Booking.agenda)).filter(Booking.id == booking_id).first()
    if not b:
        raise HTTPException(404, "Appuntamento non trovato")
    return {
        "id": b.id, "service_name": b.service_name, "scheduled_at": b.scheduled_at, "status": b.status,
        "patient_name": b.patient.user.full_name if b.patient and b.patient.user else None,
        "doctor_names": [d.full_name for d in b.doctors], "location": b.agenda.location if b.agenda else None,
    }


@router.post("/public/action")
async def public_action(payload: ReminderAction, db: Session = Depends(get_db)):
    try:
        booking_id = resolve_action_token(payload.token)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    action = payload.action.strip().lower()
    if action not in {"confirm", "cancel"}:
        raise HTTPException(400, "Azione non valida")
    b = db.query(Booking).options(joinedload(Booking.doctors)).filter(Booking.id == booking_id).first()
    if not b:
        raise HTTPException(404, "Appuntamento non trovato")
    if action == "confirm":
        if b.status != "cancelled":
            b.status = "confirmed"
        recorded = "confirmed"
    else:
        b.status = "cancelled"
        recorded = "cancelled"
        cancel_future_reminders(db, b.id, "Annullato dal paziente")
        create_offer_for_cancelled_booking(db, b)
        try:
            await delete_event(b, b.doctors)
        except Exception:
            pass
    db.add(BookingReminderResponse(booking_id=b.id, action=recorded, metadata_json=json.dumps({"source": "reminder_link"})))
    db.commit()
    return {"ok": True, "action": recorded, "status": b.status}


# CUP_REMINDER_PROVIDER_HEALTH_V1

@router.get("/providers/status")
def reminder_provider_status(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    from app.services.reminder_service import (
        provider_health,
    )

    return [
        provider_health(db, channel)
        for channel in (
            "email",
            "whatsapp",
            "sms",
            "telegram",
        )
    ]


@router.post("/providers/{channel}/reactivate")
def reminder_provider_reactivate(
    channel: str,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    from app.services.reminder_service import (
        reactivate_provider,
    )

    channel = channel.strip().lower()

    if channel not in {
        "email",
        "whatsapp",
        "sms",
        "telegram",
    }:
        raise HTTPException(
            400,
            "Canale non valido"
        )

    reactivate_provider(
        db,
        channel,
    )

    return {
        "ok": True,
        "channel": channel,
    }

# /CUP_REMINDER_PROVIDER_HEALTH_V1


# CUP_REMINDER_SHORT_LINKS_V1

from fastapi.responses import RedirectResponse
from sqlalchemy import text as sql_text
from datetime import datetime as dt_datetime


@router.get("/short/{code}", include_in_schema=False)
def resolve_reminder_short_link(
    code: str,
    db: Session = Depends(get_db),
):
    row = db.execute(
        sql_text("""
            SELECT
                target_url,
                expires_at
            FROM reminder_short_links
            WHERE code=:code
        """),
        {"code": code},
    ).mappings().first()

    if not row:
        raise HTTPException(
            404,
            "Link non trovato"
        )

    if (
        row["expires_at"]
        and row["expires_at"] < dt_datetime.utcnow()
    ):
        raise HTTPException(
            410,
            "Link scaduto"
        )

    return RedirectResponse(
        row["target_url"],
        status_code=302,
    )

# /CUP_REMINDER_SHORT_LINKS_V1
