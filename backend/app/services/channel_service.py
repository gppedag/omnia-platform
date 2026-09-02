from __future__ import annotations
from app.services.whatsapp_utils import normalize_whatsapp_number

import json
import logging
import uuid
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import settings
from app.models.chat import ChatSession
from app.models.omnichannel import ConversationChannel
from app.models.patient import Patient
from app.models.user import User
from app.services.patient_identity_service import (
    find_users_by_phone,
    normalize_phone,
)

logger = logging.getLogger("channel_service")


def resolve_patient_for_channel(db: Session, channel: str, external_id: str) -> Patient | None:
    """Risoluzione conservativa dell'identita.

    Il solo contatto proveniente da un canale NON crea mai un paziente.
    Per telefono, WhatsApp e SMS viene accettata esclusivamente una
    corrispondenza univoca sul numero normalizzato.
    """
    if channel == "telegram":
        return (
            db.query(Patient)
            .filter(Patient.reminder_telegram_chat_id == str(external_id))
            .first()
        )

    if channel in {"phone", "whatsapp", "sms"}:
        phone = normalize_phone(external_id or "")
        if not phone:
            return None

        users = find_users_by_phone(db, phone)

        # Ambiguita = nessuna associazione automatica.
        if len(users) != 1:
            return None

        return (
            db.query(Patient)
            .filter(Patient.user_id == users[0].id)
            .first()
        )

    return None


def _new_session(db: Session, channel: str, external_id: str, patient: Patient | None = None) -> ChatSession:
    sid = str(uuid.uuid4())
    session = ChatSession(
        id=sid, journey_id=sid, patient_id=patient.id if patient else None,
        channel=channel, sender_id=external_id, status="bot", context_json="{}",
    )
    db.add(session)
    db.flush()
    return session


def get_or_create_session(db: Session, channel: str, external_id: str, display_name: str = "", metadata: dict | None = None) -> ChatSession:
    link = db.query(ConversationChannel).filter(
        ConversationChannel.channel == channel,
        ConversationChannel.external_id == external_id,
    ).first()
    if link:
        session = db.query(ChatSession).filter(ChatSession.id == link.session_id).first()
        if session:
            if not session.journey_id:
                session.journey_id = session.id
            if display_name:
                link.display_name = display_name
            link.metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
            link.updated_at = func.now()
            return session

    patient = resolve_patient_for_channel(db, channel, external_id)
    session = None
    if patient:
        session = (db.query(ChatSession)
            .filter(ChatSession.patient_id == patient.id, ChatSession.status != "closed")
            .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
            .first())
    if not session:
        session = _new_session(db, channel, external_id, patient)
    elif not session.journey_id:
        session.journey_id = session.id

    if link:
        link.session_id = session.id
        link.display_name = display_name or link.display_name
        link.metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        link.updated_at = func.now()
    else:
        db.add(ConversationChannel(
            session_id=session.id, channel=channel, external_id=external_id,
            display_name=display_name or None, metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        ))
    db.flush()
    return session


def add_channel_link(db: Session, session_id: str, channel: str, external_id: str, display_name: str = "", metadata: dict | None = None):
    existing = db.query(ConversationChannel).filter(
        ConversationChannel.channel == channel, ConversationChannel.external_id == external_id,
    ).first()
    if existing:
        if existing.session_id != session_id:
            existing.session_id = session_id
        if display_name:
            existing.display_name = display_name
        existing.metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        existing.updated_at = func.now()
        return existing
    row = ConversationChannel(
        session_id=session_id, channel=channel, external_id=external_id,
        display_name=display_name or None, metadata_json=json.dumps(metadata or {}, ensure_ascii=False)
    )
    db.add(row)
    return row


def links_for_session(db: Session, session_id: str) -> list[ConversationChannel]:
    return db.query(ConversationChannel).filter(ConversationChannel.session_id == session_id).all()


def current_customer_link(db: Session, session: ChatSession) -> ConversationChannel | None:
    links = (db.query(ConversationChannel)
        .filter(ConversationChannel.session_id == session.id, ConversationChannel.channel.in_(["web", "telegram", "whatsapp", "phone", "sms"]))
        .order_by(ConversationChannel.updated_at.desc(), ConversationChannel.created_at.desc(), ConversationChannel.id.desc())
        .all())
    return links[0] if links else None


def send_outbound(db: Session, session: ChatSession, text: str, preferred_channel: str | None = None, broadcast: bool = False) -> list[dict]:
    """Invia sul canale corrente, non su tutti i canali del journey.

    Questo evita che una risposta Chatwoot venga duplicata contemporaneamente su Telegram e WhatsApp.
    """
    links = links_for_session(db, session.id)
    if preferred_channel:
        selected = [x for x in links if x.channel == preferred_channel]
    elif broadcast:
        selected = links
    else:
        current = current_customer_link(db, session)
        selected = [current] if current else []

    results = []
    for link in selected:
        if link is None:
            continue
        if link.channel == "telegram" and settings.TELEGRAM_BOT_TOKEN:
            url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
            try:
                r = httpx.post(url, json={"chat_id": link.external_id, "text": text}, timeout=15)
                results.append({"channel": "telegram", "external_id": link.external_id, "ok": r.is_success})
            except Exception as exc:
                results.append({"channel": "telegram", "external_id": link.external_id, "ok": False, "error": str(exc)})
        elif link.channel == "whatsapp" and settings.WHATSAPP_API_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID:
            url = f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
            headers = {"Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}"}
            whatsapp_target = normalize_whatsapp_number(link.external_id)
            payload = {
                "messaging_product": "whatsapp",
                "to": whatsapp_target,
                "type": "text",
                "text": {"body": text},
            }
            try:
                r = httpx.post(url, headers=headers, json=payload, timeout=15)
                results.append({"channel": "whatsapp", "external_id": link.external_id, "ok": r.is_success})
            except Exception as exc:
                results.append({"channel": "whatsapp", "external_id": link.external_id, "ok": False, "error": str(exc)})
        elif link.channel == "web":
            # Il browser legge la risposta dal DB tramite polling; nessun push esterno necessario.
            results.append({"channel": "web", "ok": True, "mode": "polling"})
        elif link.channel in {"phone", "sms"}:
            results.append({"channel": link.channel, "ok": False, "skipped": True, "reason": "dedicated_delivery_layer"})
    return results
