from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.call import Call
from app.models.chat import ChatMessage, ChatSession
from app.models.omnichannel import ConversationChannel, HandoffEvent


CHAT_LIVE_TIMEOUT_MINUTES = 15

PHONE_LIVE_STATUSES = {
    "ringing",
    "active",
    "held",
}


def _owner(session: ChatSession) -> str:
    return "operator" if session.status == "handoff" else "llm"


def _last_chat_activity(
    db: Session,
    session: ChatSession,
):
    values = [
        session.updated_at,
        session.created_at,
    ]

    message_at = (
        db.query(func.max(ChatMessage.created_at))
        .filter(ChatMessage.session_id == session.id)
        .scalar()
    )

    channel_at = (
        db.query(func.max(ConversationChannel.updated_at))
        .filter(ConversationChannel.session_id == session.id)
        .scalar()
    )

    values.extend([
        message_at,
        channel_at,
    ])

    values = [
        value
        for value in values
        if value is not None
    ]

    return max(values) if values else datetime.utcnow()


def linked_calls(
    db: Session,
    session_id: str,
):
    call_ids = [
        row[0]
        for row in (
            db.query(HandoffEvent.call_id)
            .filter(
                HandoffEvent.session_id == session_id,
                HandoffEvent.call_id.isnot(None),
            )
            .all()
        )
        if row[0]
    ]

    if not call_ids:
        return []

    return (
        db.query(Call)
        .filter(Call.id.in_(call_ids))
        .order_by(Call.started_at.desc())
        .all()
    )


def live_state(
    db: Session,
    session: ChatSession,
    close_expired: bool = False,
):
    if session.status == "closed":
        return {
            "live": False,
            "state": "closed",
            "reason": "closed",
            "owner": _owner(session),
            "expires_at": None,
            "call_id": None,
        }

    calls = linked_calls(
        db,
        session.id,
    )

    live_call = next(
        (
            call
            for call in calls
            if call.status in PHONE_LIVE_STATUSES
        ),
        None,
    )

    if live_call:
        return {
            "live": True,
            "state": "live",
            "reason": "phone_active",
            "owner": (
                "operator"
                if getattr(
                    live_call,
                    "call_type",
                    None,
                ) == "operator"
                else "llm"
            ),
            "expires_at": None,
            "call_id": live_call.id,
            "call_status": live_call.status,
            "call_type": getattr(
                live_call,
                "call_type",
                "unknown",
            ),
        }

    # Una sessione nata come phone non resta LIVE
    # dopo la chiusura della chiamata.
    if session.channel == "phone":
        return {
            "live": False,
            "state": "closed",
            "reason": "phone_ended",
            "owner": _owner(session),
            "expires_at": None,
            "call_id": (
                calls[0].id
                if calls
                else None
            ),
        }

    last_activity = _last_chat_activity(
        db,
        session,
    )

    expires_at = (
        last_activity
        + timedelta(
            minutes=CHAT_LIVE_TIMEOUT_MINUTES
        )
    )

    now = datetime.utcnow()

    if now >= expires_at:

        if (
            close_expired
            and session.status != "closed"
        ):
            previous = _owner(session)

            session.status = "closed"

            db.add(
                HandoffEvent(
                    session_id=session.id,
                    event="closed",
                    from_owner=previous,
                    to_owner="system",
                    reason=(
                        "Sessione chiusa automaticamente "
                        "per timeout di inattivita"
                    ),
                )
            )

            db.flush()

        return {
            "live": False,
            "state": "expired",
            "reason": "chat_timeout",
            "owner": _owner(session),
            "expires_at": expires_at,
            "last_activity_at": last_activity,
            "call_id": None,
        }

    return {
        "live": True,
        "state": "live",
        "reason": "chat_active",
        "owner": _owner(session),
        "expires_at": expires_at,
        "last_activity_at": last_activity,
        "call_id": None,
    }


def available_actions(
    db: Session,
    session: ChatSession,
):
    state = live_state(
        db,
        session,
        close_expired=True,
    )

    if not state["live"]:
        return state, []

    owner = state["owner"]

    if owner == "operator":
        actions = [
            "return_ai",
            "reply",
            "close",
        ]

    else:
        actions = [
            "take_operator",
            "call_operator",
            "close",
        ]

    return state, actions


def require_live(
    db: Session,
    session: ChatSession,
):
    state = live_state(
        db,
        session,
        close_expired=True,
    )

    if not state["live"]:
        db.commit()

        from fastapi import HTTPException

        raise HTTPException(
            status_code=409,
            detail=(
                "La conversazione non e piu LIVE. "
                "Avviare una nuova sessione."
            ),
        )

    return state
