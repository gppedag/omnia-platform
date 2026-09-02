from __future__ import annotations
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import require_role
from app.config import settings
from app.db.database import get_db
from app.models.chat import ChatSession, ChatMessage
from app.models.omnichannel import HandoffEvent
from app.services import chatwoot_service
from app.services.channel_service import send_outbound, current_customer_link

router = APIRouter(prefix="/api/chatwoot", tags=["chatwoot"])


@router.get("/status")
def status(db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    return {
        "enabled": chatwoot_service.enabled(),
        "hub_mode": bool(getattr(settings, "CHATWOOT_HUB_MODE", True)),
        "base_url": settings.CHATWOOT_BASE_URL,
        "account_id": settings.CHATWOOT_ACCOUNT_ID,
        "inbox_identifier_configured": bool(settings.CHATWOOT_INBOX_IDENTIFIER),
        "team_id": settings.CHATWOOT_TEAM_ID,
        "console_url": settings.CHATWOOT_BASE_URL.rstrip("/") if settings.CHATWOOT_BASE_URL else "",
        "webhook_url": (settings.CUP_PUBLIC_BASE_URL.rstrip("/") + "/api/chatwoot/webhook") if settings.CUP_PUBLIC_BASE_URL else "",
        "architecture": "Chatwoot=conversation_hub; CUP=business_source_of_truth",
    }


@router.post("/sessions/{session_id}/sync")
def sync_session(session_id: str, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Conversazione non trovata")
    result = chatwoot_service.push_history(db, session)
    db.commit()
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Sync Chatwoot fallita")
    return result


@router.post("/setup-webhook")
def setup_webhook(db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    if not settings.CUP_PUBLIC_BASE_URL:
        raise HTTPException(status_code=400, detail="CUP_PUBLIC_BASE_URL non configurato")
    callback = settings.CUP_PUBLIC_BASE_URL.rstrip("/") + "/api/chatwoot/webhook"
    result = chatwoot_service.create_webhook(callback)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result)
    return {"ok": True, "callback": callback, "chatwoot": result.get("body")}


@router.post("/webhook")
async def webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()

    # Verifica firma webhook nativa Chatwoot:
    # X-Chatwoot-Signature = sha256=HMAC_SHA256(secret, "<timestamp>.<raw_body>")
    if settings.CHATWOOT_WEBHOOK_TOKEN:
        timestamp = request.headers.get("x-chatwoot-timestamp", "")
        supplied = request.headers.get("x-chatwoot-signature", "")

        if not timestamp or not supplied:
            raise HTTPException(
                status_code=403,
                detail="Firma webhook Chatwoot mancante",
            )

        try:
            ts = int(timestamp)
        except ValueError:
            raise HTTPException(
                status_code=403,
                detail="Timestamp webhook Chatwoot non valido",
            )

        # Protezione replay: accetta webhook entro 5 minuti.
        if abs(int(time.time()) - ts) > 300:
            raise HTTPException(
                status_code=403,
                detail="Webhook Chatwoot scaduto",
            )

        signed = (
            timestamp.encode("utf-8")
            + b"."
            + raw_body
        )

        expected = "sha256=" + hmac.new(
            settings.CHATWOOT_WEBHOOK_TOKEN.encode("utf-8"),
            signed,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, supplied):
            raise HTTPException(
                status_code=403,
                detail="Firma webhook Chatwoot non valida",
            )

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Payload webhook JSON non valido",
        )
    event = payload.get("event") or payload.get("event_name") or ""
    conversation = payload.get("conversation") or {}
    conversation_id = conversation.get("id") or payload.get("conversation_id")
    if not conversation_id:
        return {"ok": True, "ignored": "conversation_id missing"}
    binding = chatwoot_service.find_binding(db, int(conversation_id))
    if not binding:
        return {"ok": True, "ignored": "conversation not mapped"}
    session = db.query(ChatSession).filter(ChatSession.id == binding.session_id).first()
    if not session:
        return {"ok": True, "ignored": "session missing"}

    if event == "message_created":
        attrs = payload.get("content_attributes") or {}
        if attrs.get("cup_origin") == "cup-system":
            return {"ok": True, "ignored": "echo"}
        private = bool(payload.get("private"))
        message_type = payload.get("message_type")
        sender_type = payload.get("sender_type") or (payload.get("sender") or {}).get("type")
        content = (payload.get("content") or "").strip()
        # Messaggi outgoing generati da un agente Chatwoot diventano messaggi operatore CUP.
        if content and not private and message_type in (1, "outgoing") and sender_type not in ("Contact", "contact"):
            session.status = "handoff"
            db.add(ChatMessage(session_id=session.id, role="operator", content=content))
            db.add(HandoffEvent(session_id=session.id, event="accepted", from_owner="llm", to_owner="operator", reason="Risposta agente Chatwoot"))
            db.commit()
            current = current_customer_link(db, session)
            outbound = send_outbound(db, session, content, preferred_channel=(current.channel if current else None))
            return {"ok": True, "action": "operator_reply", "journey_id": session.journey_id or session.id, "patient_id": session.patient_id, "current_channel": current.channel if current else None, "outbound": outbound}

    if event in {"conversation_status_changed", "conversation_updated"}:
        status = conversation.get("status") or payload.get("status")
        binding.status = status or binding.status
        if status == "resolved":
            session.status = "closed"
            db.add(HandoffEvent(session_id=session.id, event="closed", from_owner="operator", to_owner="operator", reason="Conversazione risolta in Chatwoot"))
        elif status in {"open", "pending"} and session.status != "closed":
            session.status = "handoff"
        db.commit()
        return {"ok": True, "action": "status_sync", "status": status}

    return {"ok": True, "ignored": event or "unknown"}
