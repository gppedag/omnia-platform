from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_role
from app.config import settings
from app.db.database import get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.patient import Patient
from app.services import voice_nlu_service
from app.services.channel_service import get_or_create_session


router = APIRouter(
    prefix="/api/voice-v2",
    tags=["voice-v2"],
)


class VoiceEventIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    role: str = "user"
    caller_number: str | None = None
    session_id: str | None = None
    call_id: int | None = None
    room_name: str | None = None
    operator_identity: str | None = None


HANDOFF_PATTERNS = (
    r"\boperat(?:ore|rice|orio|ori|rici)\b",
    r"\bpersona\s+(?:vera|reale|umana)\b",
    r"\bparlare\s+con\s+(?:qualcuno|una\s+persona)\b",
    r"\bassistenza\s+umana\b",
    r"\bpass(?:ami|atemi)\b",
    r"\btrasferisc\w*\b",
)

BOOKING_PATTERNS = (
    r"\bprenot\w*\b",
    r"\bvisita\b",
    r"\besame\b",
    r"\bappuntament",
    r"\bdisponibilit",
)

RESCHEDULE_PATTERNS = (
    r"\bspost\w*\b",
    r"\bcambi\w*\s+(?:data|giorno|ora|appuntament)",
)

CANCEL_PATTERNS = (
    r"\bannull\w*\b",
    r"\bcancell\w*\b",
    r"\bdisdic\w*\b",
)

NEGATIVE_PATTERNS = (
    r"\bfatica\b",
    r"\bdifficolt",
    r"\bproblema\b",
    r"\bnon\s+riesco\b",
    r"\bperdendo\s+tempo\b",
    r"\bfrustr",
    r"\barrabbi",
    r"\binsoddisf",
    r"\bnon\s+mi\s+va\s+bene\b",
    r"\bnon\s+va\s+bene\b",
    r"\bnon\s+funziona\b",
    r"\bimpossibile\b",
)

POSITIVE_PATTERNS = (
    r"\bgrazie\b",
    r"\bperfetto\b",
    r"\bottimo\b",
    r"\beccellente\b",
    r"\bsoddisfatt",
)


def service_auth(token: str | None):
    expected = (
        getattr(settings, "VOICE_AI_SERVICE_TOKEN", "")
        or getattr(settings, "HANDOFF_SERVICE_TOKEN", "")
        or ""
    ).strip()

    if not expected:
        raise HTTPException(
            status_code=503,
            detail="VOICE_AI_SERVICE_TOKEN non configurato",
        )

    if token != expected:
        raise HTTPException(
            status_code=401,
            detail="Service token non valido",
        )


def matches(text: str, patterns) -> bool:
    value = " ".join((text or "").lower().split())

    return any(
        re.search(pattern, value, flags=re.I)
        for pattern in patterns
    )


def resolve_session(
    db: Session,
    payload: VoiceEventIn,
) -> ChatSession | None:

    if payload.session_id:
        row = (
            db.query(ChatSession)
            .filter(ChatSession.id == payload.session_id)
            .first()
        )

        if row:
            return row

    if payload.caller_number:
        return get_or_create_session(
            db,
            "phone",
            payload.caller_number,
            payload.caller_number,
            {
                "source": "voice_v2",
                "room_name": payload.room_name,
            },
        )

    return None


def base_nlu(text: str) -> dict[str, Any]:
    for fn_name in (
        "analyze_voice_text",
        "analyze_text",
        "analyze",
    ):
        fn = getattr(
            voice_nlu_service,
            fn_name,
            None,
        )

        if not callable(fn):
            continue

        try:
            result = fn(text)

            if isinstance(result, dict):
                return result

        except Exception:
            pass

    return {}


def deterministic_analysis(
    text: str,
) -> dict[str, Any]:

    base = base_nlu(text)

    handoff = matches(
        text,
        HANDOFF_PATTERNS,
    )

    if handoff:
        intent = "human_handoff"
        confidence = 0.99

    elif matches(text, CANCEL_PATTERNS):
        intent = "cancel"
        confidence = 0.95

    elif matches(text, RESCHEDULE_PATTERNS):
        intent = "reschedule"
        confidence = 0.93

    elif matches(text, BOOKING_PATTERNS):
        intent = "booking"
        confidence = 0.92

    else:
        intent = base.get("intent") or "information"

        if intent == "unknown":
            intent = "information"

        confidence = max(
            float(base.get("confidence") or 0),
            0.60,
        )

    if matches(text, NEGATIVE_PATTERNS):
        sentiment = "negative"
        score = -1.0

    elif matches(text, POSITIVE_PATTERNS):
        sentiment = "positive"
        score = 1.0

    else:
        sentiment = base.get(
            "sentiment",
            "neutral",
        )

        if sentiment not in (
            "positive",
            "neutral",
            "negative",
        ):
            sentiment = "neutral"

        score = {
            "positive": 1.0,
            "neutral": 0.0,
            "negative": -1.0,
        }[sentiment]

    return {
        "intent": intent,
        "confidence": confidence,
        "sentiment": sentiment,
        "sentiment_score": score,
        "short_summary": (
            base.get("short_summary")
            or text[:500]
        ),
        "handoff": handoff,
        "handoff_reason": (
            "explicit_user_request"
            if handoff
            else None
        ),
        "decision_source": (
            "deterministic+hybrid"
        ),
    }


def update_context(
    session: ChatSession,
    analysis: dict[str, Any],
    payload: VoiceEventIn,
):

    try:
        ctx = json.loads(
            session.context_json
            or "{}"
        )

        if not isinstance(ctx, dict):
            ctx = {}

    except Exception:
        ctx = {}

    voice = ctx.get("voice")

    if not isinstance(voice, dict):
        voice = {}

    history = voice.get(
        "sentiment_history"
    )

    if not isinstance(history, list):
        history = []

    history.append({
        "sentiment": analysis["sentiment"],
        "score": analysis["sentiment_score"],
        "text": payload.text[:300],
    })

    history = history[-30:]

    scores = [
        float(
            item.get("score")
            or 0
        )
        for item in history
    ]

    average = (
        sum(scores) / len(scores)
        if scores
        else 0.0
    )

    if average <= -0.25:
        overall = "negative"

    elif average >= 0.25:
        overall = "positive"

    else:
        overall = "neutral"

    trend = "stable"

    if len(scores) >= 3:
        recent = (
            sum(scores[-2:]) / 2
        )

        previous = (
            sum(scores[:-2])
            / max(
                1,
                len(scores[:-2]),
            )
        )

        delta = recent - previous

        if delta <= -0.35:
            trend = "worsening"

        elif delta >= 0.35:
            trend = "improving"

    voice.update({
        "sentiment": (
            analysis["sentiment"]
        ),
        "sentiment_overall": overall,
        "sentiment_score": round(
            average,
            3,
        ),
        "sentiment_trend": trend,
        "sentiment_history": history,
        "intent": analysis["intent"],
        "confidence": analysis["confidence"],
        "short_summary": (
            analysis["short_summary"]
        ),
        "caller_number": (
            payload.caller_number
        ),
        "room_name": payload.room_name,
        "handoff": (
            analysis["handoff"]
        ),
        "handoff_reason": (
            analysis["handoff_reason"]
        ),
        "decision_source": (
            analysis["decision_source"]
        ),
    })

    ctx["voice"] = voice

    session.context_json = json.dumps(
        ctx,
        ensure_ascii=False,
        separators=(",", ":"),
    )


@router.post("/event")
def voice_event(
    payload: VoiceEventIn,
    x_voice_ai_token: str | None = Header(
        default=None
    ),
    db: Session = Depends(get_db),
):

    service_auth(x_voice_ai_token)

    role = (
        payload.role
        or "user"
    ).lower().strip()

    if role not in {
        "user",
        "assistant",
        "operator",
        "system",
    }:
        raise HTTPException(
            status_code=400,
            detail="Ruolo non valido",
        )

    text = payload.text.strip()

    session = resolve_session(
        db,
        payload,
    )

    if not session:
        raise HTTPException(
            status_code=409,
            detail="Sessione phone non risolta",
        )

    previous = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id
            == session.id
        )
        .order_by(
            ChatMessage.id.desc()
        )
        .first()
    )

    created = False

    if not (
        previous
        and previous.role == role
        and (
            previous.content
            or ""
        ).strip() == text
    ):
        db.add(
            ChatMessage(
                session_id=session.id,
                role=role,
                content=text,
            )
        )

        created = True

    analysis = None

    if role == "user":
        analysis = deterministic_analysis(
            text
        )

        update_context(
            session,
            analysis,
            payload,
        )

    elif (
        role == "system"
        and "operatore" in text.lower()
    ):
        try:
            ctx = json.loads(
                session.context_json
                or "{}"
            )

            if not isinstance(ctx, dict):
                ctx = {}

        except Exception:
            ctx = {}

        voice = ctx.get("voice")

        if not isinstance(voice, dict):
            voice = {}

        voice.update({
            "handoff": True,
            "handoff_status": (
                "operator_joined"
            ),
            "handoff_operator": (
                payload.operator_identity
            ),
        })

        ctx["voice"] = voice

        session.context_json = json.dumps(
            ctx,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    db.commit()

    response = {
        "status": "ok",
        "created": created,
        "session_id": session.id,
        "role": role,
        "handoff": bool(
            (analysis or {}).get(
                "handoff"
            )
        ),
    }

    if analysis:
        response.update(analysis)

    return response


@router.get("/conversations")
def conversations(
    limit: int = 100,
    current_user=Depends(
        require_role(
            "operator",
            "admin",
        )
    ),
    db: Session = Depends(get_db),
):

    limit = max(
        1,
        min(limit, 200),
    )

    sessions = (
        db.query(ChatSession)
        .filter(
            ChatSession.channel
            == "phone"
        )
        .order_by(
            ChatSession.updated_at.desc()
        )
        .limit(limit)
        .all()
    )

    result = []

    for session in sessions:
        try:
            ctx = json.loads(
                session.context_json
                or "{}"
            )

        except Exception:
            ctx = {}

        voice = ctx.get(
            "voice",
            {},
        )

        messages = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id
                == session.id
            )
            .order_by(
                ChatMessage.created_at.asc(),
                ChatMessage.id.asc(),
            )
            .all()
        )

        patient = None
        patient_user = None

        if session.patient_id:
            patient = (
                db.query(Patient)
                .filter(Patient.id == session.patient_id)
                .first()
            )

        patient_name = None
        patient_phone = None
        patient_email = None

        if patient:
            # 1. Campi diretti sul Patient
            patient_name = (
                getattr(patient, "full_name", None)
                or getattr(patient, "name", None)
                or " ".join(
                    part
                    for part in (
                        getattr(patient, "first_name", None),
                        getattr(patient, "last_name", None),
                    )
                    if part
                ).strip()
                or None
            )

            patient_phone = (
                getattr(patient, "phone", None)
                or getattr(patient, "mobile", None)
                or getattr(patient, "phone_number", None)
            )

            patient_email = getattr(
                patient,
                "email",
                None,
            )

            # 2. Se Patient e collegato a User, usa anche User
            user_id = (
                getattr(patient, "user_id", None)
                or getattr(patient, "account_id", None)
            )

            if user_id:
                try:
                    from app.models.user import User

                    patient_user = (
                        db.query(User)
                        .filter(User.id == user_id)
                        .first()
                    )

                except Exception:
                    patient_user = None

            if patient_user:
                patient_name = (
                    patient_name
                    or getattr(patient_user, "full_name", None)
                    or getattr(patient_user, "name", None)
                    or " ".join(
                        part
                        for part in (
                            getattr(patient_user, "first_name", None),
                            getattr(patient_user, "last_name", None),
                        )
                        if part
                    ).strip()
                    or None
                )

                patient_phone = (
                    patient_phone
                    or getattr(patient_user, "phone", None)
                )

                patient_email = (
                    patient_email
                    or getattr(patient_user, "email", None)
                )

            # 3. Ultimo fallback: cerca un User con stesso telefono
            if not patient_name and session.sender_id:
                try:
                    from app.models.user import User

                    phone_user = (
                        db.query(User)
                        .filter(User.phone == session.sender_id)
                        .first()
                    )

                    if phone_user:
                        patient_name = (
                            getattr(phone_user, "full_name", None)
                            or getattr(phone_user, "name", None)
                            or None
                        )

                        patient_email = (
                            patient_email
                            or getattr(phone_user, "email", None)
                        )

                except Exception:
                    pass

        result.append({
            "id": session.id,
            "sender_id": session.sender_id,
            "patient_id": session.patient_id,
            "patient_name": patient_name,
            "patient_phone": patient_phone,
            "patient_email": patient_email,
            "reconciled": bool(session.patient_id),
            "status": session.status,
            "created_at": (
                session.created_at.isoformat()
                if session.created_at
                else None
            ),
            "updated_at": (
                session.updated_at.isoformat()
                if session.updated_at
                else None
            ),
            "voice": voice,
            "message_count": len(messages),
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    "created_at": (
                        message.created_at.isoformat()
                        if message.created_at
                        else None
                    ),
                }
                for message in messages
            ],
        })

    return {
        "items": result,
        "count": len(result),
    }
