from __future__ import annotations
import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_role
from app.config import settings
from app.db.database import get_db, SessionLocal
from app.models.chat import ChatSession
from app.models.call import Call
from app.models.handoff import OperatorHandoff, OperatorPresence
from app.models.user import User
from app.services import handoff_service
from app.services.asterisk_gateway import originate_operator_call

router = APIRouter(prefix="/api/handoffs", tags=["handoffs"])


class ServiceHandoffRequest(BaseModel):
    session_id: str | None = None
    call_id: int | None = None
    reason: str = Field(default="Richiesta operatore umano", max_length=1000)
    source: str = "livekit"
    caller_number: str | None = None
    summary: str | None = None


class PresenceRequest(BaseModel):
    status: str
    extension: str | None = None


class QueueManager:
    def __init__(self):
        self.clients: list[WebSocket] = []
    async def connect(self, ws: WebSocket):
        await ws.accept(); self.clients.append(ws)
    def disconnect(self, ws: WebSocket):
        if ws in self.clients: self.clients.remove(ws)
    async def broadcast(self, payload: dict):
        for ws in list(self.clients):
            try: await ws.send_json(payload)
            except Exception: self.disconnect(ws)

manager = QueueManager()


def _serialize(h: OperatorHandoff, db: Session):
    session = db.query(ChatSession).filter(ChatSession.id == h.session_id).first()
    call = db.query(Call).filter(Call.id == h.call_id).first() if h.call_id else None
    return {
        "id": h.id, "session_id": h.session_id, "call_id": h.call_id, "source": h.source,
        "status": h.status, "mode": h.mode, "fallback_action": h.fallback_action,
        "reason": h.reason, "summary": h.summary, "requested_at": h.requested_at,
        "expires_at": h.expires_at, "ringing_at": h.ringing_at, "accepted_at": h.accepted_at,
        "operator_id": h.operator_id,
        "caller_number": call.caller_number if call else (session.sender_id if session else None),
        "channel": session.channel if session else h.source,
        "last_message": session.messages[-1].content if session and session.messages else "",
    }


def _service_auth(token: str | None):
    expected = (getattr(settings, "HANDOFF_SERVICE_TOKEN", "") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="HANDOFF_SERVICE_TOKEN non configurato")
    if token != expected:
        raise HTTPException(status_code=401, detail="Service token non valido")


@router.post("/request")
async def request_from_voice(payload: ServiceHandoffRequest, x_handoff_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    _service_auth(x_handoff_token)
    session = db.query(ChatSession).filter(ChatSession.id == payload.session_id).first() if payload.session_id else None
    if not session and payload.call_id:
        from app.models.omnichannel import HandoffEvent
        ev = db.query(HandoffEvent).filter(HandoffEvent.call_id == payload.call_id).order_by(HandoffEvent.created_at.desc()).first()
        if ev: session = db.query(ChatSession).filter(ChatSession.id == ev.session_id).first()
    if not session and payload.caller_number:
        from app.models.omnichannel import ConversationChannel
        link = db.query(ConversationChannel).filter(ConversationChannel.channel == "phone", ConversationChannel.external_id == payload.caller_number).order_by(ConversationChannel.created_at.desc()).first()
        if link: session = db.query(ChatSession).filter(ChatSession.id == link.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Journey/sessione non trovata: indica session_id, call_id o caller_number")
    handoff, created = handoff_service.create_request(db, session, payload.reason, payload.source, payload.call_id, payload.summary)
    if handoff_service.available_operators(db, handoff_service.handoff_channel(handoff)):
        handoff_service.mark_ringing(db, handoff)
    db.commit(); db.refresh(handoff)
    await manager.broadcast({"type": "handoff_requested", "handoff": _serialize(handoff, db)})
    return {"ok": True, "created": created, "handoff": _serialize(handoff, db), "message": "Rimani in linea, sto cercando un operatore."}


@router.get("/queue")
def queue(db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    rows = db.query(OperatorHandoff).filter(OperatorHandoff.status.in_(handoff_service.OPEN_STATES)).order_by(OperatorHandoff.requested_at.asc()).all()
    return [_serialize(x, db) for x in rows if handoff_service.user_can_handle(user, x)]


@router.get("/recent")
def recent(db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    rows = db.query(OperatorHandoff).order_by(OperatorHandoff.requested_at.desc()).limit(100).all()
    return [_serialize(x, db) for x in rows if handoff_service.user_can_handle(user, x)]


@router.post("/{handoff_id}/accept")
async def accept(handoff_id: int, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    h = db.query(OperatorHandoff).filter(OperatorHandoff.id == handoff_id).with_for_update().first()
    if not h: raise HTTPException(status_code=404, detail="Handoff non trovato")
    if not handoff_service.user_can_handle(user, h): raise HTTPException(status_code=403, detail="Operatore non abilitato a questo canale")
    if not handoff_service.accept(db, h, user):
        raise HTTPException(status_code=409, detail="Richiesta già acquisita o non più disponibile")
    db.commit(); db.refresh(h)
    if settings.ASTERISK_HANDOFF_ENABLED and h.source in {"livekit", "phone", "voice"}:
        asyncio.create_task(originate_operator_call(h.session_id, _serialize(h, db).get("caller_number") or ""))
    await manager.broadcast({"type": "handoff_accepted", "handoff": _serialize(h, db), "operator_id": user.id})
    return {"ok": True, "handoff": _serialize(h, db)}


@router.post("/{handoff_id}/reject")
async def reject(handoff_id: int, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    h = db.query(OperatorHandoff).filter(OperatorHandoff.id == handoff_id).first()
    if not h: raise HTTPException(status_code=404, detail="Handoff non trovato")
    if not handoff_service.user_can_handle(user, h): raise HTTPException(status_code=403, detail="Operatore non abilitato a questo canale")
    if not handoff_service.reject(db, h, user):
        raise HTTPException(status_code=409, detail="Richiesta non più disponibile")
    db.commit(); await manager.broadcast({"type": "handoff_rejected", "handoff_id": h.id, "operator_id": user.id})
    return {"ok": True}


@router.post("/{handoff_id}/return-ai")
async def return_ai(handoff_id: int, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    h = db.query(OperatorHandoff).filter(OperatorHandoff.id == handoff_id).first()
    if not h: raise HTTPException(status_code=404, detail="Handoff non trovato")
    if not handoff_service.user_can_handle(user, h): raise HTTPException(status_code=403, detail="Operatore non abilitato a questo canale")
    h.fallback_action = "return_ai"; handoff_service.apply_fallback(db, h); db.commit()
    await manager.broadcast({"type": "handoff_resolved", "handoff_id": h.id, "status": h.status})
    return {"ok": True, "status": h.status}


@router.post("/{handoff_id}/callback")
async def callback(handoff_id: int, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    h = db.query(OperatorHandoff).filter(OperatorHandoff.id == handoff_id).first()
    if not h: raise HTTPException(status_code=404, detail="Handoff non trovato")
    if not handoff_service.user_can_handle(user, h): raise HTTPException(status_code=403, detail="Operatore non abilitato a questo canale")
    h.fallback_action = "callback"; handoff_service.apply_fallback(db, h); db.commit()
    await manager.broadcast({"type": "handoff_resolved", "handoff_id": h.id, "status": h.status})
    return {"ok": True, "status": h.status}


@router.get("/presence")
def presence(db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    rows = db.query(OperatorPresence, User).join(User, User.id == OperatorPresence.user_id).all()
    return [{"user_id": p.user_id, "full_name": u.full_name, "status": p.status, "extension": p.extension, "updated_at": p.updated_at} for p,u in rows]


@router.put("/presence/me")
async def set_presence(payload: PresenceRequest, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    if payload.status not in {"available", "busy", "offline"}: raise HTTPException(status_code=400, detail="Stato non valido")
    p = db.query(OperatorPresence).filter(OperatorPresence.user_id == user.id).first()
    if not p: p = OperatorPresence(user_id=user.id); db.add(p)
    p.status = payload.status
    if payload.extension is not None: p.extension = payload.extension
    db.commit(); db.refresh(p)
    await manager.broadcast({"type": "presence", "user_id": user.id, "status": p.status})
    return {"ok": True, "status": p.status, "extension": p.extension}


@router.websocket("/ws")
async def ws_queue(ws: WebSocket, token: str = ""):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if not payload.get("sub"): raise JWTError("sub mancante")
    except Exception:
        await ws.close(code=4401); return
    await manager.connect(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


async def timeout_worker():
    while True:
        await asyncio.sleep(2)
        db = SessionLocal()
        changed = []
        auto_accepted = []
        try:
            now = datetime.utcnow()
            open_rows = db.query(OperatorHandoff).filter(OperatorHandoff.status.in_(handoff_service.OPEN_STATES)).order_by(OperatorHandoff.requested_at.asc()).all()
            for h in open_rows:
                available = handoff_service.available_operators(db, handoff_service.handoff_channel(h))
                if h.status == "waiting_operator" and available:
                    handoff_service.mark_ringing(db, h)
                if h.mode == "auto_answer" and available and h.status in handoff_service.OPEN_STATES:
                    operator, _presence = available.pop(0)
                    if handoff_service.accept(db, h, operator):
                        auto_accepted.append((h.id, h.session_id, operator.id))
            rows = [h for h in open_rows if h.status in handoff_service.OPEN_STATES and h.expires_at and h.expires_at <= now]
            for h in rows:
                status = handoff_service.apply_fallback(db, h)
                changed.append((h.id, status))
            if changed or auto_accepted or open_rows: db.commit()
        finally:
            db.close()
        for hid, sid, operator_id in auto_accepted:
            if settings.ASTERISK_HANDOFF_ENABLED:
                asyncio.create_task(originate_operator_call(sid, ""))
            await manager.broadcast({"type": "handoff_accepted", "handoff_id": hid, "operator_id": operator_id, "auto": True})
        for hid, status in changed:
            await manager.broadcast({"type": "handoff_timeout", "handoff_id": hid, "status": status})
