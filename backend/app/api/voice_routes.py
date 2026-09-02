from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_role
from app.config import settings
from app.db.database import get_db
from app.models.call import Call
from app.models.chat import ChatSession, ChatMessage
from app.services import handoff_service, voice_nlu_service, chatwoot_service
from app.services.channel_service import get_or_create_session

router = APIRouter(prefix="/api/voice", tags=["voice-ai"])


class VoiceAnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    call_id: int | None = None
    session_id: str | None = None
    caller_number: str | None = None
    failed_understandings: int = Field(default=0, ge=0, le=20)
    context: list[dict] = Field(default_factory=list)


def _service_auth(token: str | None):
    expected = (getattr(settings, "VOICE_AI_SERVICE_TOKEN", "") or getattr(settings, "HANDOFF_SERVICE_TOKEN", "") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="VOICE_AI_SERVICE_TOKEN/HANDOFF_SERVICE_TOKEN non configurato")
    if token != expected:
        raise HTTPException(status_code=401, detail="Service token non valido")


def _resolve_session(db: Session, payload: VoiceAnalyzeRequest):
    if payload.session_id:
        row = db.query(ChatSession).filter(ChatSession.id == payload.session_id).first()
        if row:
            return row
    if payload.call_id:
        from app.models.omnichannel import HandoffEvent
        ev = db.query(HandoffEvent).filter(HandoffEvent.call_id == payload.call_id).order_by(HandoffEvent.created_at.desc()).first()
        if ev:
            row = db.query(ChatSession).filter(ChatSession.id == ev.session_id).first()
            if row:
                return row
    if payload.caller_number:
        # Il numero telefonico viene collegato allo stesso journey attivo del paziente, se riconoscibile.
        session = get_or_create_session(db, "phone", payload.caller_number, payload.caller_number, {"source": "voice_nlu"})
        if chatwoot_service.enabled():
            try:
                chatwoot_service.ensure_binding(db, session)
            except Exception:
                pass
        return session
    return None


@router.get("/status")
def status():
    return {
        "voice_nlu_enabled": bool(getattr(settings, "VOICE_NLU_ENABLED", True)),
        "llm_configured": voice_nlu_service.llm_available(),
        "model": settings.LLM_MODEL if voice_nlu_service.llm_available() else None,
        "domain_limited": True,
        "confidence_threshold": float(getattr(settings, "VOICE_NLU_CONFIDENCE_THRESHOLD", 0.62)),
        "sentiment_enabled": bool(getattr(settings, "VOICE_SENTIMENT_ENABLED", True)),
        "booking_decisions_use_llm": False,
    }



class VoiceTranscriptIn(BaseModel):
    text: str
    role: str = "user"
    caller_number: str | None = None
    call_id: int | None = None
    room_name: str | None = None
    operator_identity: str | None = None


@router.post("/transcript")
def ingest_livekit_transcript(
    payload: VoiceTranscriptIn,
    x_voice_ai_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _service_auth(x_voice_ai_token)
    """Persistenza transcript proveniente dal LiveKit Voice Agent."""

    role = (payload.role or "user").strip().lower()

    if role not in {"user", "assistant", "operator", "system"}:
        raise HTTPException(status_code=400, detail="Invalid transcript role")

    text = (payload.text or "").strip()

    if not text:
        raise HTTPException(status_code=400, detail="Empty transcript")

    # Riutilizza la stessa risoluzione sessione del canale Voice.
    analyze_payload = VoiceAnalyzeIn(
        text=text,
        caller_number=payload.caller_number,
        call_id=payload.call_id,
    )

    session = _resolve_session(db, analyze_payload)

    if not session:
        raise HTTPException(
            status_code=409,
            detail="Unable to resolve phone conversation",
        )

    # Evita duplicati consecutivi prodotti dagli eventi LiveKit.
    previous = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id.desc())
        .first()
    )

    created = False

    if not (
        previous
        and previous.role == role
        and (previous.content or "").strip() == text
    ):
        db.add(
            ChatMessage(
                session_id=session.id,
                role=role,
                content=text,
            )
        )
        created = True

    result = None

    # Il sentiment riguarda il paziente, non ciò che dice l'assistente.
    if role == "user":
        result = analyze_voice_text(text)

        try:
            ctx = json.loads(session.context_json or "{}")
            if not isinstance(ctx, dict):
                ctx = {}
        except Exception:
            ctx = {}

        voice_ctx = ctx.get("voice")
        if not isinstance(voice_ctx, dict):
            voice_ctx = {}

        voice_ctx.update({
            "sentiment": result.get("sentiment"),
            "intent": result.get("intent"),
            "confidence": float(result.get("confidence") or 0.0),
            "short_summary": result.get("short_summary") or text[:500],
            "call_id": payload.call_id,
            "caller_number": payload.caller_number,
            "room_name": payload.room_name,
            "handoff": bool(result.get("handoff")),
            "handoff_reason": result.get("handoff_reason"),
        })

        ctx["voice"] = voice_ctx
        session.context_json = json.dumps(
            ctx,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    db.commit()

    return {
        "status": "ok",
        "created": created,
        "session_id": session.id,
        "role": role,
        "analysis": result,
    }


class VoiceMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    role: str = "assistant"
    call_id: int | None = None
    session_id: str | None = None
    caller_number: str | None = None
    room_name: str | None = None


@router.post("/message")
def voice_message(
    payload: VoiceMessageRequest,
    x_voice_ai_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _service_auth(x_voice_ai_token)
    role = (payload.role or "assistant").strip().lower()
    if role not in {"assistant", "operator", "system"}:
        raise HTTPException(status_code=400, detail="Ruolo transcript non valido")
    text = (payload.text or "").strip()
    session = _resolve_session(db, payload)
    if not session:
        raise HTTPException(status_code=409, detail="Sessione telefonica non risolta")
    previous = (db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.id.desc()).first())
    created = False
    if text and not (previous and previous.role == role and (previous.content or "").strip() == text):
        db.add(ChatMessage(session_id=session.id, role=role, content=text))
        created = True
    db.commit()
    return {"status": "ok", "created": created, "session_id": session.id, "role": role}


@router.post("/analyze")
def analyze_voice(
    payload: VoiceAnalyzeRequest,
    x_voice_ai_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    _service_auth(x_voice_ai_token)
    result = voice_nlu_service.analyze(payload.text, payload.context)
    result = voice_nlu_service.apply_policy(result, payload.failed_understandings)

    call = db.query(Call).filter(Call.id == payload.call_id).first() if payload.call_id else None
    if call:
        call.ai_intent = result.get("intent")
        call.ai_sentiment = result.get("sentiment") if getattr(settings, "VOICE_SENTIMENT_ENABLED", True) else None
        call.ai_confidence = int(round(float(result.get("confidence") or 0.0) * 100))
        call.ai_last_summary = result.get("short_summary") or payload.text[:500]

    handoff_created = False
    session = _resolve_session(db, payload)

    # -----------------------------------------------------
    # Persistenza conversazione Voice
    # -----------------------------------------------------
    if session:
        # Salva ogni utterance finale ricevuta dalla Voice AI
        db.add(ChatMessage(
            session_id=session.id,
            role="user",
            content=payload.text.strip(),
        ))

        # Mantiene sulla sessione lo stato NLU più recente.
        try:
            ctx = json.loads(session.context_json or "{}")
            if not isinstance(ctx, dict):
                ctx = {}
        except Exception:
            ctx = {}

        voice_ctx = ctx.get("voice")
        if not isinstance(voice_ctx, dict):
            voice_ctx = {}

        voice_ctx.update({
            "sentiment": (
                result.get("sentiment")
                if getattr(settings, "VOICE_SENTIMENT_ENABLED", True)
                else None
            ),
            "intent": result.get("intent"),
            "confidence": float(result.get("confidence") or 0.0),
            "short_summary": result.get("short_summary") or payload.text[:500],
            "call_id": payload.call_id,
            "caller_number": payload.caller_number,
            "handoff": bool(result.get("handoff")),
            "handoff_reason": result.get("handoff_reason"),
        })

        ctx["voice"] = voice_ctx
        session.context_json = json.dumps(
            ctx,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    if result.get("handoff") and session:
        handoff, handoff_created = handoff_service.create_request(
            db,
            session,
            result.get("handoff_reason") or "Escalation voice AI",
            source="voice",
            call_id=payload.call_id,
            summary=result.get("short_summary") or payload.text[:500],
        )
        if handoff_service.available_operators(db, "phone"):
            handoff_service.mark_ringing(db, handoff)
        result["handoff_id"] = handoff.id
    elif result.get("handoff"):
        result["handoff_pending_session_resolution"] = True

    db.commit()
    result["handoff_created"] = handoff_created
    return result
