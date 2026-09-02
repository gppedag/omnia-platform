from __future__ import annotations
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from urllib.parse import quote
from jose import jwt, JWTError
from sqlalchemy.orm import joinedload

from app.config import settings
from app.models.waitlist import WaitlistEntry, WaitlistOffer, WaitlistOfferRecipient
from app.models.booking import Booking
from app.models.patient import Patient
from app.services.reminder_service import _send_sms, _send_whatsapp, _send_telegram, _send_email, ensure_booking_reminders



def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _matches(entry: WaitlistEntry, booking: Booking) -> bool:
    slot = booking.scheduled_at
    if entry.visit_type_id and booking.visit_type_id and entry.visit_type_id != booking.visit_type_id:
        return False
    if entry.agenda_id and entry.agenda_id != booking.agenda_id:
        return False
    if entry.doctor_id and all(d.id != entry.doctor_id for d in (booking.doctors or [])):
        return False
    if entry.preferred_from and slot < entry.preferred_from:
        return False
    if entry.preferred_to and slot > entry.preferred_to:
        return False
    hm = slot.strftime('%H:%M')
    if entry.preferred_time_from and hm < entry.preferred_time_from:
        return False
    if entry.preferred_time_to and hm > entry.preferred_time_to:
        return False
    return True


def _target(patient: Patient, channel: str):
    user = patient.user
    if channel in {'sms','whatsapp'}: return user.phone if user else None
    if channel == 'email': return user.email if user else None
    if channel == 'telegram': return patient.reminder_telegram_chat_id
    return None


def _channels(entry: WaitlistEntry, patient: Patient):
    raw = entry.channels or patient.reminder_channels or settings.REMINDER_CHANNELS or 'sms,email'
    return [x.strip().lower() for x in raw.split(',') if x.strip().lower() in {'sms','whatsapp','email','telegram'}]


def _token(recipient: WaitlistOfferRecipient, offer: WaitlistOffer):
    payload = {'sub': recipient.token_id, 'purpose': 'waitlist_offer', 'exp': int(offer.expires_at.replace(tzinfo=timezone.utc).timestamp())}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _url(recipient, offer):
    base = settings.CUP_PUBLIC_BASE_URL.rstrip('/')
    path = '/waitlist.html?token=' + quote(_token(recipient, offer), safe='')
    return base + path if base else path


def _send(channel, target, text):
    try:
        if channel == 'sms': return _send_sms(target, text)
        if channel == 'whatsapp': return _send_whatsapp(target, text)
        if channel == 'telegram': return _send_telegram(target, text)
        if channel == 'email': return _send_email(target, text)
    except Exception as exc:
        return False, str(exc)
    return False, 'Canale non supportato'


def create_offer_for_cancelled_booking(db, booking: Booking):
    if not settings.WAITLIST_ENABLED or not booking.agenda_id or booking.scheduled_at <= _now():
        return None
    existing = db.query(WaitlistOffer).filter(WaitlistOffer.source_booking_id == booking.id, WaitlistOffer.status == 'open').first()
    if existing: return existing
    entries = db.query(WaitlistEntry).options(joinedload(WaitlistEntry.patient).joinedload(Patient.user)).filter(WaitlistEntry.status == 'waiting').order_by(WaitlistEntry.priority.desc(), WaitlistEntry.created_at.asc()).all()
    candidates = [e for e in entries if _matches(e, booking)][:max(1, settings.WAITLIST_MAX_CANDIDATES)]
    if not candidates: return None
    offer = WaitlistOffer(source_booking_id=booking.id, agenda_id=booking.agenda_id, visit_type_id=booking.visit_type_id,
                          scheduled_at=booking.scheduled_at, end_at=booking.end_at or booking.scheduled_at + timedelta(minutes=30),
                          expires_at=min(booking.scheduled_at, _now() + timedelta(minutes=max(1, settings.WAITLIST_OFFER_TTL_MINUTES))), status='open')
    db.add(offer); db.flush()
    for entry in candidates:
        patient = entry.patient
        selected_channel = None; target = None
        for channel in _channels(entry, patient):
            t = _target(patient, channel)
            if t: selected_channel, target = channel, t; break
        rec = WaitlistOfferRecipient(offer_id=offer.id, waitlist_entry_id=entry.id, patient_id=entry.patient_id,
                                     token_id=uuid4().hex, channel=selected_channel, target=target,
                                     status='offered' if target else 'failed')
        db.add(rec); db.flush()
        entry.status = 'offered'
        if target:
            text = f"Si e liberato un appuntamento per {booking.service_name} il {booking.scheduled_at.strftime('%d/%m/%Y')} alle {booking.scheduled_at.strftime('%H:%M')}. Lo slot sara assegnato al primo che accetta: {_url(rec, offer)}"
            ok, response = _send(selected_channel, target, text)
            rec.sent_at = _now(); rec.provider_response = response
            if not ok: rec.status = 'failed'; entry.status = 'waiting'
    db.commit(); db.refresh(offer)
    return offer


def resolve_token(token: str):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError('Proposta non valida o scaduta') from exc
    if payload.get('purpose') != 'waitlist_offer': raise ValueError('Proposta non valida')
    return payload['sub']


def accept_offer(db, token: str):
    token_id = resolve_token(token)
    rec = db.query(WaitlistOfferRecipient).filter(WaitlistOfferRecipient.token_id == token_id).with_for_update().first()
    if not rec: raise ValueError('Proposta non trovata')
    offer = db.query(WaitlistOffer).filter(WaitlistOffer.id == rec.offer_id).with_for_update().first()
    if not offer or offer.status != 'open' or offer.expires_at < _now():
        if offer and offer.status == 'open': offer.status = 'expired'
        rec.status = 'expired'; db.commit(); raise ValueError('Questo slot non e piu disponibile')
    # Verifica finale anti-conflitto: lo slot deve essere ancora libero nell'agenda.
    conflict = db.query(Booking).filter(Booking.agenda_id == offer.agenda_id, Booking.status != 'cancelled',
        Booking.scheduled_at < offer.end_at, Booking.end_at > offer.scheduled_at).first()
    if conflict:
        offer.status = 'expired'; db.commit(); raise ValueError('Lo slot e gia stato assegnato')
    entry = db.get(WaitlistEntry, rec.waitlist_entry_id)
    source = db.get(Booking, offer.source_booking_id) if offer.source_booking_id else None
    booking = Booking(patient_id=rec.patient_id, service_name=(source.service_name if source else (offer.visit_type.name if offer.visit_type else 'Visita')),
                      scheduled_at=offer.scheduled_at, end_at=offer.end_at, agenda_id=offer.agenda_id,
                      visit_type_id=offer.visit_type_id, status='confirmed', priority='normal', notes='Prenotato automaticamente da lista d attesa')
    if source: booking.doctors = list(source.doctors)
    db.add(booking); db.flush()
    offer.status='booked'; offer.accepted_patient_id=rec.patient_id; offer.accepted_booking_id=booking.id
    rec.status='accepted'; rec.responded_at=_now(); entry.status='booked'
    for other in offer.recipients:
        if other.id != rec.id and other.status in {'offered','failed'}:
            other.status='expired'; other.responded_at=_now()
            if other.entry and other.entry.status == 'offered': other.entry.status='waiting'
    db.commit(); db.refresh(booking)
    booking = db.query(Booking).options(joinedload(Booking.patient).joinedload(Patient.user), joinedload(Booking.doctors), joinedload(Booking.agenda), joinedload(Booking.visit_type)).filter(Booking.id==booking.id).first()
    ensure_booking_reminders(db, booking, include_confirmation=True)
    return booking


def expire_open_offers(db):
    rows = db.query(WaitlistOffer).filter(WaitlistOffer.status == 'open', WaitlistOffer.expires_at < _now()).all()
    changed = 0
    for offer in rows:
        offer.status = 'expired'; changed += 1
        for rec in offer.recipients:
            if rec.status == 'offered':
                rec.status = 'expired'; rec.responded_at = _now()
                if rec.entry and rec.entry.status == 'offered': rec.entry.status = 'waiting'
    if changed: db.commit()
    return changed


async def waitlist_worker():
    import asyncio
    from app.db.database import SessionLocal
    while True:
        db = SessionLocal()
        try:
            expire_open_offers(db)
        except Exception:
            db.rollback()
        finally:
            db.close()
        await asyncio.sleep(60)
