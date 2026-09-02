from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.config import settings
from app.models.chat import ChatMessage, ChatSession
from app.models.call import Call
from app.models.handoff import OperatorHandoff, OperatorPresence
from app.models.omnichannel import HandoffEvent
from app.models.user import User

OPEN_STATES = {"requested", "waiting_operator", "ringing"}
FINAL_STATES = {"accepted", "rejected", "timeout", "returned_to_ai", "callback_requested", "voicemail", "failed", "closed"}


def _utcnow():
    return datetime.utcnow()


def _summary(session: ChatSession) -> str:
    messages = list(session.messages or [])[-8:]
    parts = []
    for m in messages:
        if m.role in {"user", "assistant"}:
            parts.append(f"{m.role}: {m.content[:300]}")
    return "\n".join(parts)[-1800:]


def get_open_for_session(db: Session, session_id: str):
    return (
        db.query(OperatorHandoff)
        .filter(OperatorHandoff.session_id == session_id, OperatorHandoff.status.in_(OPEN_STATES))
        .order_by(OperatorHandoff.requested_at.desc())
        .first()
    )


def create_request(db: Session, session: ChatSession, reason: str, source: str = "chat", call_id: int | None = None, summary: str | None = None):
    existing = get_open_for_session(db, session.id)
    if existing:
        return existing, False
    timeout = max(5, int(getattr(settings, "HANDOFF_TIMEOUT_SECONDS", 30)))
    mode = getattr(settings, "HANDOFF_MODE", "manual")
    fallback = getattr(settings, "HANDOFF_TIMEOUT_ACTION", "callback")
    now = _utcnow()
    row = OperatorHandoff(
        session_id=session.id,
        call_id=call_id,
        source=source or session.channel or "chat",
        status="waiting_operator",
        mode=mode,
        fallback_action=fallback,
        reason=reason,
        summary=summary or _summary(session),
        expires_at=now + timedelta(seconds=timeout),
    )
    session.status = "handoff"
    db.add(row)
    db.flush()
    db.add(HandoffEvent(session_id=session.id, event="requested", from_owner="llm", to_owner="operator", reason=reason, call_id=call_id))
    db.add(HandoffEvent(session_id=session.id, event="waiting_operator", from_owner="llm", to_owner="operator", reason=f"Coda operatore · modalità {mode}", call_id=call_id))
    db.add(ChatMessage(session_id=session.id, role="system", content="Richiesta operatore inserita in coda. In attesa di accettazione."))
    return row, True


def available_operators(db: Session, channel: str | None = None):
    rows = (
        db.query(User, OperatorPresence)
        .join(OperatorPresence, OperatorPresence.user_id == User.id)
        .filter(User.role.in_(["admin", "operator"]), User.is_active.is_(True), OperatorPresence.status == "available")
        .all()
    )
    if channel == "phone":
        rows = [(u, p) for u, p in rows if u.role == "admin" or bool(u.can_phone)]
    elif channel == "chat":
        rows = [(u, p) for u, p in rows if u.role == "admin" or bool(u.can_chat)]
    return rows


def handoff_channel(handoff: OperatorHandoff) -> str:
    return "phone" if handoff.call_id or (handoff.source or "").lower() in {"livekit", "phone", "voice", "asterisk"} else "chat"


def user_can_handle(user: User, handoff: OperatorHandoff) -> bool:
    if user.role == "admin":
        return True
    return bool(user.can_phone) if handoff_channel(handoff) == "phone" else bool(user.can_chat)


def mark_ringing(db: Session, handoff: OperatorHandoff):
    if handoff.status not in {"waiting_operator", "requested"}:
        return False
    handoff.status = "ringing"
    handoff.ringing_at = _utcnow()
    db.add(HandoffEvent(session_id=handoff.session_id, event="ringing", from_owner="queue", to_owner="operator", reason="Notifica inviata agli operatori disponibili", call_id=handoff.call_id))
    return True


def accept(db: Session, handoff: OperatorHandoff, operator: User):
    if handoff.status not in OPEN_STATES:
        return False
    handoff.status = "accepted"
    handoff.operator_id = operator.id
    handoff.accepted_at = _utcnow()
    handoff.resolved_at = handoff.accepted_at
    session = db.query(ChatSession).filter(ChatSession.id == handoff.session_id).first()
    if session:
        session.status = "handoff"
        db.add(ChatMessage(session_id=session.id, role="system", content=f"Operatore {operator.full_name} ha accettato la richiesta."))
    if handoff.call_id:
        call = db.query(Call).filter(Call.id == handoff.call_id).first()
        if call and call.status in {"ringing", "held"}:
            call.status = "active"
    presence = db.query(OperatorPresence).filter(OperatorPresence.user_id == operator.id).first()
    if presence:
        presence.status = "busy"
    db.add(HandoffEvent(session_id=handoff.session_id, event="accepted", from_owner="queue", to_owner="operator", operator_id=operator.id, reason="Richiesta accettata", call_id=handoff.call_id))
    return True


def reject(db: Session, handoff: OperatorHandoff, operator: User):
    if handoff.status not in OPEN_STATES:
        return False
    rejected = {x for x in (handoff.rejected_by or "").split(",") if x}
    rejected.add(str(operator.id))
    handoff.rejected_by = ",".join(sorted(rejected))
    db.add(HandoffEvent(session_id=handoff.session_id, event="rejected", from_owner="operator", to_owner="queue", operator_id=operator.id, reason="Operatore non disponibile", call_id=handoff.call_id))
    return True


def apply_fallback(db: Session, handoff: OperatorHandoff):
    if handoff.status not in OPEN_STATES:
        return handoff.status
    action = handoff.fallback_action or "callback"
    session = db.query(ChatSession).filter(ChatSession.id == handoff.session_id).first()
    now = _utcnow()
    if action == "keep_waiting":
        handoff.status = "waiting_operator"
        handoff.expires_at = now + timedelta(seconds=max(5, int(settings.HANDOFF_TIMEOUT_SECONDS)))
        db.add(HandoffEvent(session_id=handoff.session_id, event="timeout", from_owner="queue", to_owner="queue", reason="Timeout: permanenza in coda", call_id=handoff.call_id))
        return "waiting_operator"
    if action == "return_ai":
        handoff.status = "returned_to_ai"
        if session:
            session.status = "bot"
            db.add(ChatMessage(session_id=session.id, role="system", content="Nessun operatore disponibile: gestione restituita all'AI."))
        db.add(HandoffEvent(session_id=handoff.session_id, event="returned_to_llm", from_owner="queue", to_owner="llm", reason="Timeout operatore", call_id=handoff.call_id))
    elif action == "voicemail":
        handoff.status = "voicemail"
        db.add(HandoffEvent(session_id=handoff.session_id, event="voicemail", from_owner="queue", to_owner="operator", reason="Timeout: richiesta messaggio/voicemail", call_id=handoff.call_id))
    else:
        handoff.status = "callback_requested"
        db.add(HandoffEvent(session_id=handoff.session_id, event="callback_requested", from_owner="queue", to_owner="operator", reason="Timeout: richiamata richiesta", call_id=handoff.call_id))
    handoff.resolved_at = now
    return handoff.status
