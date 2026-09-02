from __future__ import annotations
import asyncio
import uuid
import hmac
import hashlib
import json
from pathlib import Path
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Query, Header
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.auth import require_role, require_operator_channel
from app.config import settings
from app.db.database import get_db
from app.models.chat import ChatAttachment, ChatMessage, ChatSession
from app.models.call import Call
from app.models.omnichannel import ConversationChannel, HandoffEvent
from app.models.patient_relationship import PatientRelationship
from app.services.channel_service import add_channel_link, get_or_create_session, links_for_session, send_outbound, current_customer_link, resolve_patient_for_channel, _new_session
from app.services.asterisk_gateway import originate_operator_call
from app.services.sms_service import continuation_url, resolve_continuation_token, send_continuation_sms
from app.services import llm_service, chatwoot_service, handoff_service
from app.services.live_session_service import available_actions, require_live, live_state

router = APIRouter(prefix="/api/omnichannel", tags=["omnichannel"])


class HandoffRequest(BaseModel):
    reason: str = Field(default="Richiesta assistenza umana", max_length=1000)
    call_operator: bool = True

class SmsLinkRequest(BaseModel):
    phone: str | None = None



class OwnerRequest(BaseModel):
    owner: str




def _store_attachment(db: Session, session: ChatSession, filename: str, content: bytes, mime_type: str = "application/octet-stream"):
    if not content:
        return None
    if len(content) > settings.CHAT_MAX_UPLOAD_BYTES:
        return None
    safe = Path(filename or "documento").name[:255]
    suffix = Path(safe).suffix.lower() or ".bin"
    session_dir = Path(settings.CHAT_UPLOAD_DIR) / session.id
    session_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{suffix}"
    (session_dir / stored).write_bytes(content)
    row = ChatAttachment(session_id=session.id, original_filename=safe, stored_filename=stored, mime_type=mime_type, size_bytes=len(content))
    db.add(row)
    db.add(ChatMessage(session_id=session.id, role="user", content=f"Documento ricevuto via {session.channel}: {safe}"))
    return row


def _download_whatsapp_media(media_id: str):
    if not media_id or not settings.WHATSAPP_API_TOKEN:
        return None
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}"}
    meta_url = f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}/{media_id}"
    meta = httpx.get(meta_url, headers=headers, timeout=20)
    meta.raise_for_status()
    data = meta.json()
    media = httpx.get(data["url"], headers=headers, timeout=30)
    media.raise_for_status()
    return media.content, media.headers.get("content-type", data.get("mime_type", "application/octet-stream"))


def _download_telegram_file(file_id: str):
    if not file_id or not settings.TELEGRAM_BOT_TOKEN:
        return None
    base = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
    meta = httpx.get(base + "/getFile", params={"file_id": file_id}, timeout=20)
    meta.raise_for_status()
    path = meta.json()["result"]["file_path"]
    media = httpx.get(f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{path}", timeout=30)
    media.raise_for_status()
    return media.content, media.headers.get("content-type", "application/octet-stream"), Path(path).name

def _patient_booking_url() -> str:
    path = (getattr(settings, "PATIENT_BOOKING_PATH", "") or "/patient-portal.html?view=booking").strip()
    base = (getattr(settings, "CUP_PUBLIC_BASE_URL", "") or "").rstrip("/")
    return (base + path) if base and path.startswith("/") else path


def _owner(session: ChatSession) -> str:
    return "operator" if session.status == "handoff" else "llm"


def _history(session: ChatSession):
    return [{"role": m.role, "content": m.content} for m in session.messages]


def process_external(db: Session, channel: str, external_id: str, text: str, display_name: str = "", metadata: dict | None = None):
    session = get_or_create_session(db, channel, external_id, display_name, metadata)
    db.add(ChatMessage(session_id=session.id, role="user", content=text))
    if session.status == "handoff":
        # In hub mode il messaggio viene consegnato a Chatwoot senza risposta automatica: parla l'operatore.
        reply = None
    else:
        low = " ".join((text or "").lower().split())
        if any(k in low for k in ("prenota", "prenotazione", "prenotare", "vorrei una visita", "fissare una visita")):
            reply = f"Per prenotare usa la funzione Prenota del sito, con disponibilita e prezzi aggiornati: {_patient_booking_url()}"
            handoff = False
        else:
            try:
                reply, handoff = llm_service.reply(_history(session), text, db=db)
            except Exception:
                reply, handoff = ("Ho ricevuto il messaggio. Posso aiutarti su servizi CUP e documenti. Per assistenza umana scrivi OPERATORE.", False)
        if handoff or "operatore" in low:
            handoff_service.create_request(db, session, "Richiesta da canale esterno", source=channel)
    if reply:
        db.add(ChatMessage(session_id=session.id, role="assistant", content=reply))
    db.commit()
    if chatwoot_service.enabled():
        try:
            chatwoot_service.push_message(db, session, text, "user")
            if reply:
                chatwoot_service.push_message(db, session, reply, "assistant")
            # Tutti i messaggi vengono sincronizzati in tempo reale: al passaggio operatore basta aprire la conversazione.
            if session.status == "handoff" and settings.CHATWOOT_AUTO_SYNC_HANDOFF:
                chatwoot_service.set_status(db, session, "open")
            db.commit()
        except Exception:
            pass
    if reply:
        send_outbound(db, session, reply, preferred_channel=channel)
    return session, reply or ""


@router.get("/whatsapp/webhook")
def whatsapp_verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=403, detail="Verify token non valido")


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    raw = await request.body()
    if settings.WHATSAPP_APP_SECRET:
        signature = request.headers.get("x-hub-signature-256", "")
        expected = "sha256=" + hmac.new(settings.WHATSAPP_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=403, detail="Firma WhatsApp non valida")
    payload = json.loads(raw or b"{}")
    processed = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for msg in value.get("messages", []) or []:
                sender = msg.get("from", "")
                if not sender:
                    continue
                text = (msg.get("text") or {}).get("body")
                session = get_or_create_session(db, "whatsapp", sender, contacts.get(sender, ""), {"message_id": msg.get("id")})
                media_info = msg.get("document") or msg.get("image")
                if media_info and media_info.get("id"):
                    try:
                        downloaded = _download_whatsapp_media(media_info["id"])
                        if downloaded:
                            content, mime = downloaded
                            filename = media_info.get("filename") or f"whatsapp-{media_info['id']}"
                            attachment = _store_attachment(db, session, filename, content, mime)
                            db.commit()
                            if attachment and chatwoot_service.enabled():
                                try:
                                    db.refresh(attachment)
                                    chatwoot_service.push_attachment_note(db, session, attachment)
                                    db.commit()
                                except Exception:
                                    pass
                            processed += 1
                    except Exception:
                        pass
                if text:
                    session, _ = process_external(db, "whatsapp", sender, text, contacts.get(sender, ""), {"message_id": msg.get("id")})
                    processed += 1
    return {"ok": True, "processed": processed}


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    if settings.TELEGRAM_WEBHOOK_SECRET:
        supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
        if supplied != settings.TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Secret Telegram non valido")
    payload = await request.json()
    message = payload.get("message") or payload.get("edited_message") or {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    text = message.get("text") or message.get("caption")
    if not chat.get("id"):
        return {"ok": True, "processed": 0}
    name = " ".join(x for x in [sender.get("first_name", ""), sender.get("last_name", "")] if x).strip()
    telegram_id = str(chat["id"])

    # Telegram /start apre sempre una nuova conversazione CUP.
    # La vecchia sessione resta nello storico e il link Telegram
    # viene spostato sulla nuova sessione.
    if text and text.strip() and text.strip().split()[0].lower() == "/start":
        link = db.query(ConversationChannel).filter(
            ConversationChannel.channel == "telegram",
            ConversationChannel.external_id == telegram_id,
        ).first()

        old_session = None
        if link:
            old_session = db.query(ChatSession).filter(
                ChatSession.id == link.session_id
            ).first()

        if old_session:
            if old_session.status != "closed":
                old_session.status = "closed"

            db.add(ChatMessage(
                session_id=old_session.id,
                role="system",
                content="Conversazione chiusa da Telegram con /start.",
            ))

            if chatwoot_service.enabled():
                try:
                    from app.models.chatwoot import ChatwootBinding
                    binding = db.query(ChatwootBinding).filter(
                        ChatwootBinding.session_id == old_session.id
                    ).first()
                    if binding:
                        chatwoot_service.set_status(
                            db, old_session, "resolved"
                        )
                except Exception:
                    pass

        patient = resolve_patient_for_channel(
            db, "telegram", telegram_id
        )

        session = _new_session(
            db, "telegram", telegram_id, patient
        )

        metadata = {
            "message_id": message.get("message_id"),
            "telegram_start": True,
        }

        if link:
            link.session_id = session.id
            link.display_name = name or link.display_name
            link.metadata_json = json.dumps(
                metadata, ensure_ascii=False
            )
            link.updated_at = func.now()
        else:
            db.add(ConversationChannel(
                session_id=session.id,
                channel="telegram",
                external_id=telegram_id,
                display_name=name or None,
                metadata_json=json.dumps(
                    metadata, ensure_ascii=False
                ),
            ))

        welcome = (
            "Ciao! Hai iniziato una nuova conversazione CUP. "
            "Come posso aiutarti?"
        )

        db.add(ChatMessage(
            session_id=session.id,
            role="assistant",
            content=welcome,
        ))

        db.commit()

        send_outbound(
            db,
            session,
            welcome,
            preferred_channel="telegram",
        )

        return {
            "ok": True,
            "processed": 1,
            "session_id": session.id,
            "new_session": True,
        }

    session = get_or_create_session(
        db,
        "telegram",
        telegram_id,
        name,
        {"message_id": message.get("message_id")},
    )
    document = message.get("document")
    photo = (message.get("photo") or [])[-1:]
    file_id = document.get("file_id") if document else (photo[0].get("file_id") if photo else None)
    if file_id:
        try:
            downloaded = _download_telegram_file(file_id)
            if downloaded:
                content, mime, path_name = downloaded
                filename = (document or {}).get("file_name") or path_name
                attachment = _store_attachment(db, session, filename, content, mime)
                db.commit()
                if attachment and chatwoot_service.enabled():
                    try:
                        db.refresh(attachment)
                        chatwoot_service.push_attachment_note(db, session, attachment)
                        db.commit()
                    except Exception:
                        pass
        except Exception:
            pass
    if text:
        session, reply = process_external(db, "telegram", str(chat["id"]), text, name, {"message_id": message.get("message_id")})
    return {"ok": True, "processed": 1, "session_id": session.id}




@router.get("/journeys/active")
def active_journeys(db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    rows = (db.query(ChatSession)
        .filter(ChatSession.status != "closed")
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        .limit(12).all())
    result = []
    try:
        from app.models.chatwoot import ChatwootBinding
    except Exception:
        ChatwootBinding = None
    for session in rows:
        links = sorted(links_for_session(db, session.id), key=lambda x: x.created_at or session.created_at)
        handoffs = db.query(HandoffEvent).filter(HandoffEvent.session_id == session.id).order_by(HandoffEvent.created_at).all()
        steps = []
        if links:
            for link in links:
                if link.channel not in steps:
                    steps.append(link.channel)
        elif session.channel:
            steps.append(session.channel)
        event_map = {"phone_started":"phone", "sms_sent":"sms", "web_opened":"web", "requested":"handoff", "waiting_operator":"handoff", "ringing":"handoff", "accepted":"operator", "callback_requested":"operator", "voicemail":"operator"}
        for event in handoffs:
            step = event_map.get(event.event)
            if step and (not steps or steps[-1] != step):
                steps.append(step)
        if session.attachments and (not steps or steps[-1] != "documents"):
            steps.append("documents")
        cw = None
        if ChatwootBinding is not None:
            b = db.query(ChatwootBinding).filter(ChatwootBinding.session_id == session.id).first()
            if b:
                cw = {
                    "conversation_id": b.conversation_id,
                    "status": b.status,
                    "url": f"{settings.CHATWOOT_BASE_URL.rstrip('/')}/app/accounts/{settings.CHATWOOT_ACCOUNT_ID}/conversations/{b.conversation_id}" if settings.CHATWOOT_BASE_URL else None,
                }
                if not steps or steps[-1] != "chatwoot":
                    steps.append("chatwoot")
        origin = links[0].channel if links else (session.channel or "web")
        current = links[-1].channel if links else (session.channel or "web")
        result.append({
            "id": session.id, "journey_id": session.journey_id or session.id, "patient_id": session.patient_id, "status": session.status, "owner": _owner(session),
            "origin_channel": origin, "current_channel": current, "steps": steps,
            "attachments": len(session.attachments), "updated_at": session.updated_at or session.created_at,
            "last_message": session.messages[-1].content if session.messages else "", "chatwoot": cw,
        })
    return result


@router.get("/sessions/{session_id}")
def conversation_detail(session_id: str, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Conversazione non trovata")
    links = links_for_session(db, session_id)
    links = sorted(links, key=lambda x: x.created_at or session.created_at)
    handoffs = db.query(HandoffEvent).filter(HandoffEvent.session_id == session_id).order_by(HandoffEvent.created_at).all()

    call_ids = [h.call_id for h in handoffs if h.call_id]
    calls = {}
    if call_ids:
        calls = {c.id: c for c in db.query(Call).filter(Call.id.in_(call_ids)).all()}

    cw = None
    try:
        from app.models.chatwoot import ChatwootBinding
        b = db.query(ChatwootBinding).filter(ChatwootBinding.session_id == session_id).first()
        if b:
            cw = {
                "conversation_id": b.conversation_id,
                "status": b.status,
                "url": f"{settings.CHATWOOT_BASE_URL.rstrip('/')}/app/accounts/{settings.CHATWOOT_ACCOUNT_ID}/conversations/{b.conversation_id}" if settings.CHATWOOT_BASE_URL else None,
            }
    except Exception:
        pass

    journey = [{
        "type": "session", "channel": session.channel or "web", "label": "Richiesta avviata",
        "detail": f"Journey {session.id[:8]}", "created_at": session.created_at,
    }]
    for x in links:
        journey.append({
            "type": "channel", "channel": x.channel,
            "label": f"Canale {x.channel}",
            "detail": x.display_name or x.external_id,
            "created_at": x.created_at,
        })
    for h in handoffs:
        call = calls.get(h.call_id) if h.call_id else None
        detail = h.reason or f"{h.from_owner} → {h.to_owner}"
        if call:
            detail = f"{detail} · {call.caller_number or '-'} → {call.callee_number or '-'} · {call.status}"
        journey.append({
            "type": "call" if h.call_id else "handoff",
            "channel": "phone" if h.call_id else None,
            "label": {
                "phone_started": "Telefonata Asterisk",
                "sms_sent": "SMS inviato",
                "web_opened": "Pagina web aperta",
                "requested": "Handoff richiesto",
                "waiting_operator": "In coda operatore",
                "ringing": "Operatori notificati",
                "accepted": "Operatore in carico",
                "rejected": "Operatore ha rifiutato",
                "timeout": "Timeout operatore",
                "callback_requested": "Callback richiesta",
                "voicemail": "Messaggio / voicemail",
                "returned_to_llm": "Restituita all'AI",
                "closed": "Conversazione chiusa",
                "failed": "Handoff fallito",
            }.get(h.event, h.event.replace("_", " ").title()),
            "detail": detail, "event": h.event, "call_id": h.call_id,
            "created_at": h.created_at,
        })
    for a in session.attachments:
        journey.append({
            "type": "attachment", "channel": "web", "label": "Documento caricato",
            "detail": a.original_filename, "created_at": a.created_at,
        })
    if cw:
        journey.append({
            "type": "chatwoot", "channel": "chatwoot", "label": "Chatwoot",
            "detail": f"Conversazione #{cw['conversation_id']} · {cw['status']}",
            "created_at": session.updated_at or session.created_at,
            "url": cw.get("url"),
        })
    journey.sort(key=lambda x: x.get("created_at") or session.created_at)

    origin_channel = links[0].channel if links else (session.channel or "web")
    current_channel = links[-1].channel if links else (session.channel or "web")
    state, actions = available_actions(
        db,
        session,
    )

    db.commit()

    return {
        "id": session.id,
        "journey_id": session.journey_id or session.id,
        "patient_id": session.patient_id,
        "status": session.status,
        "owner": state["owner"],
        "live": state["live"],
        "live_state": state["state"],
        "live_reason": state["reason"],
        "live_expires_at": state.get("expires_at"),
        "available_actions": actions,
        "origin_channel": origin_channel,
        "current_channel": current_channel,
        "channels": [{"channel": x.channel, "external_id": x.external_id, "display_name": x.display_name, "created_at": x.created_at} for x in links],
        "handoffs": [{"id": h.id, "event": h.event, "from_owner": h.from_owner, "to_owner": h.to_owner, "reason": h.reason, "call_id": h.call_id, "created_at": h.created_at} for h in handoffs],
        "journey": journey,
        "chatwoot_enabled": chatwoot_service.enabled(),
        "chatwoot": cw,
    }



# ============================================================
# OMNIA_LIVE_DOC_EXCHANGE_V1
# Scambio documenti durante telefonata operatore.
#
# Riutilizza:
# - ChatSession / ConversationChannel
# - continuation token CUP
# - upload documentale chatbot esistente
# - SMS / WhatsApp / Telegram esistenti
#
# Telegram viene proposto SOLO se il paziente e' riconciliato
# con un record Patient che contiene reminder_telegram_chat_id.
# ============================================================


def _omnia_doc_phone(value):
    value = (value or "").strip()
    if not value:
        return None

    if value.lower() in {
        "<unknown>",
        "unknown",
        "anonymous",
        "anonymous@anonymous.invalid",
    }:
        return None

    return value


def _omnia_doc_call_context(db, call_id: int):
    from app.models.call import Call
    from app.models.patient import Patient
    from app.services.channel_service import resolve_patient_for_channel

    call = db.query(Call).filter(
        Call.id == call_id
    ).first()

    if not call:
        raise HTTPException(
            status_code=404,
            detail="Chiamata non trovata",
        )

    patient = None

    if getattr(call, "patient_id", None):
        patient = db.query(Patient).filter(
            Patient.id == call.patient_id
        ).first()

    phone = _omnia_doc_phone(
        getattr(call, "caller_number", None)
    )

    # Riconciliazione conservativa:
    # soltanto corrispondenza telefonica esatta normalizzata
    # tramite il servizio omnicanale esistente.
    if not patient and phone:
        try:
            patient = resolve_patient_for_channel(
                db,
                "phone",
                phone,
            )
        except Exception:
            patient = None

    # Se la chiamata non espone il numero ma il paziente e'
    # gia' riconciliato, usa il telefono dell'anagrafica.
    if not phone and patient:
        user_row = getattr(patient, "user", None)
        phone = _omnia_doc_phone(
            getattr(user_row, "phone", None)
        )

    return call, patient, phone


def _resolve_document_recipient(db, patient, default_phone, payload):
    recipient_type = str(
        payload.get("recipient_type") or "patient"
    ).strip().lower()

    if recipient_type == "patient":
        user_row = getattr(patient, "user", None) if patient else None
        phone = _omnia_doc_phone(
            getattr(user_row, "phone", None)
            if user_row else default_phone
        )
        return {
            "type": "patient",
            "relationship_id": None,
            "name": getattr(user_row, "full_name", None)
                    if user_row else "Paziente",
            "phone": phone,
        }

    if recipient_type == "relationship":
        relationship_id = payload.get("relationship_id")
        if not relationship_id:
            raise HTTPException(400, "Delegato non specificato")

        row = db.query(PatientRelationship).filter(
            PatientRelationship.id == int(relationship_id),
            PatientRelationship.patient_id == patient.id,
            PatientRelationship.is_active.is_(True),
        ).first()

        if not row:
            raise HTTPException(404, "Delegato non trovato")

        if not row.can_receive_document_requests:
            raise HTTPException(
                403,
                "Delegato non autorizzato a ricevere richieste documenti"
            )

        return {
            "type": "relationship",
            "relationship_id": row.id,
            "name": row.display_name or "Delegato",
            "phone": _omnia_doc_phone(row.phone),
        }

    if recipient_type == "manual":
        phone = _omnia_doc_phone(payload.get("recipient_phone"))
        if not phone:
            raise HTTPException(400, "Numero destinatario non valido")

        return {
            "type": "manual",
            "relationship_id": None,
            "name": str(
                payload.get("recipient_name") or "Altro contatto"
            ).strip(),
            "phone": phone,
        }

    raise HTTPException(400, "Tipo destinatario non valido")


def _omnia_doc_recipients(db, patient, patient_phone):
    recipients = []

    user_row = getattr(patient, "user", None) if patient else None

    if patient and patient_phone:
        recipients.append({
            "id": "patient",
            "type": "patient",
            "label": (
                getattr(user_row, "full_name", None)
                or "Paziente"
            ),
            "relationship_type": "patient",
            "phone": patient_phone,
        })

    if patient:
        rows = (
            db.query(PatientRelationship)
            .filter(
                PatientRelationship.patient_id == patient.id,
                PatientRelationship.is_active.is_(True),
                PatientRelationship.can_receive_document_requests.is_(True),
            )
            .order_by(
                PatientRelationship.is_primary.desc(),
                PatientRelationship.id.asc(),
            )
            .all()
        )

        for row in rows:
            if not row.phone:
                continue

            recipients.append({
                "id": f"relationship:{row.id}",
                "type": "relationship",
                "relationship_id": row.id,
                "label": row.display_name or "Delegato",
                "relationship_type": row.relationship_type,
                "phone": row.phone,
            })

    recipients.append({
        "id": "manual",
        "type": "manual",
        "label": "Altro cellulare",
        "relationship_type": "manual",
        "phone": None,
    })

    return recipients


def _omnia_doc_channels(db, call_id: int):
    call, patient, phone = _omnia_doc_call_context(
        db,
        call_id,
    )

    # OMNIA_DOC_PATIENT_PHONE_PRIORITY_V1
    #
    # Per document exchange il destinatario deve essere il PAZIENTE,
    # non l'interno telefonico dell'operatore (es. 201/202).
    #
    # Se il paziente e' stato riconciliato, l'anagrafica e' la
    # fonte autorevole del numero. Il numero della Call resta
    # soltanto come fallback quando il paziente non ha telefono.
    if patient:
        user_row = getattr(patient, "user", None)

        patient_phone = _omnia_doc_phone(
            getattr(user_row, "phone", None)
            if user_row
            else None
        )

        if patient_phone:
            phone = patient_phone
    # /OMNIA_DOC_PATIENT_PHONE_PRIORITY_V1

    channels = []

    # SMS: disponibile quando abbiamo un numero.
    if phone:
        channels.append({
            "id": "sms",
            "label": "SMS",
        })

    # WhatsApp: stesso numero telefonico, ma soltanto
    # se Cloud API e Phone Number ID sono configurati.
    if (
        phone
        and settings.WHATSAPP_API_TOKEN
        and settings.WHATSAPP_PHONE_NUMBER_ID
    ):
        channels.append({
            "id": "whatsapp",
            "label": "WhatsApp",
        })

    telegram_chat_id = None

    # IMPORTANTE:
    # Telegram NON viene mai dedotto dal numero.
    # Deve esistere esplicitamente nell'anagrafica Patient.
    if patient:
        telegram_chat_id = (
            getattr(
                patient,
                "reminder_telegram_chat_id",
                None,
            )
            or None
        )

    if (
        patient
        and telegram_chat_id
        and settings.TELEGRAM_BOT_TOKEN
    ):
        channels.append({
            "id": "telegram",
            "label": "Telegram",
        })

    user_row = (
        getattr(patient, "user", None)
        if patient
        else None
    )

    return {
        "call": call,
        "patient": patient,
        "phone": phone,
        "telegram_chat_id": telegram_chat_id,
        "patient_name": (
            getattr(user_row, "full_name", None)
            if user_row
            else None
        ),
        "channels": channels,
    }


def _omnia_doc_find_session(
    db,
    call_id: int,
    session_id: str | None = None,
):
    if session_id:
        session = db.query(ChatSession).filter(
            ChatSession.id == session_id
        ).first()

        if session:
            try:
                ctx = json.loads(
                    session.context_json or "{}"
                )
            except Exception:
                ctx = {}

            doc = ctx.get(
                "document_exchange",
                {},
            )

            if str(
                doc.get("call_id")
            ) == str(call_id):
                return session

    # Recupero anche dopo refresh del browser.
    candidates = (
        db.query(ChatSession)
        .order_by(
            ChatSession.updated_at.desc(),
            ChatSession.created_at.desc(),
        )
        .limit(100)
        .all()
    )

    for session in candidates:
        try:
            ctx = json.loads(
                session.context_json or "{}"
            )
        except Exception:
            continue

        doc = ctx.get(
            "document_exchange",
            {},
        )

        if str(
            doc.get("call_id")
        ) == str(call_id):
            return session

    return None


@router.get(
    "/calls/{call_id}/document-channels"
)
def omnia_document_channels(
    call_id: int,
    db: Session = Depends(get_db),
    user=Depends(
        require_role(
            "admin",
            "operator",
        )
    ),
):
    info = _omnia_doc_channels(
        db,
        call_id,
    )

    call = info["call"]
    patient = info["patient"]

    return {
        "ok": True,
        "call_id": call.id,
        "call_status": call.status,
        "patient_id": (
            patient.id
            if patient
            else None
        ),
        "patient_name": info[
            "patient_name"
        ],
        "phone": info["phone"],
        "telegram_linked": bool(
            info["telegram_chat_id"]
        ),
        "channels": info["channels"],
        "recipients": _omnia_doc_recipients(
            db,
            patient,
            info["phone"],
        ),
    }


@router.post(
    "/calls/{call_id}/document-link"
)
def omnia_send_document_link(
    call_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user=Depends(
        require_role(
            "admin",
            "operator",
        )
    ),
):
    from app.services.reminder_service import (
        _send_whatsapp,
        _send_telegram,
    )

    info = _omnia_doc_channels(
        db,
        call_id,
    )

    call = info["call"]
    patient = info["patient"]
    phone = info["phone"]

    recipient = _resolve_document_recipient(
        db,
        patient,
        phone,
        payload,
    )
    recipient_phone = recipient.get("phone")
    recipient_name = recipient.get("name")

    if (
        recipient.get("type") == "manual"
        and bool(payload.get("save_recipient"))
        and patient
    ):
        relationship_type = str(
            payload.get("recipient_relationship")
            or "other"
        ).strip().lower()

        existing = (
            db.query(PatientRelationship)
            .filter(
                PatientRelationship.patient_id == patient.id,
                PatientRelationship.phone == recipient_phone,
                PatientRelationship.is_active.is_(True),
            )
            .first()
        )

        if not existing:
            saved_relationship = PatientRelationship(
                patient_id=patient.id,
                relationship_type=relationship_type,
                display_name=recipient_name or "Contatto",
                phone=recipient_phone,
                can_book=False,
                can_manage_bookings=False,
                can_receive_reminders=False,
                can_receive_document_requests=True,
                can_send_documents=True,
                authorization_type="informal",
                is_primary=False,
                is_active=True,
            )

            db.add(saved_relationship)
            db.flush()

            recipient["relationship_id"] = saved_relationship.id

    channel = str(
        payload.get("channel")
        or ""
    ).strip().lower()

    allowed = {
        row["id"]
        for row in info["channels"]
    }

    if channel not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Canale non disponibile per questo paziente",
        )

    requested_type = str(
        payload.get("document_type")
        or "documento"
    ).strip().lower()

    labels = {
        "prescrizione": "la prescrizione",
        "impegnativa": "l'impegnativa",
        "referto": "il referto",
        "documento": "il documento",
        "altro": "il documento richiesto",
    }

    document_label = labels.get(
        requested_type,
        "il documento richiesto",
    )

    display_name = (
        info["patient_name"]
        or phone
        or "Paziente"
    )

    if not phone:
        raise HTTPException(
            status_code=400,
            detail="Numero telefonico non disponibile",
        )

    # Usa la stessa Journey omnicanale del paziente.
    session = get_or_create_session(
        db,
        "phone",
        phone,
        display_name,
        {
            "source": "omnia_voice",
            "call_id": call.id,
        },
    )

    if (
        patient
        and not session.patient_id
    ):
        session.patient_id = patient.id

    try:
        ctx = json.loads(
            session.context_json or "{}"
        )
    except Exception:
        ctx = {}

    ctx["document_exchange"] = {
        "call_id": call.id,
        "requested_by": getattr(
            user,
            "id",
            None,
        ),
        "document_type": requested_type,
        "channel": channel,
        "recipient_type": recipient.get("type"),
        "relationship_id": recipient.get("relationship_id"),
        "recipient_name": recipient_name,
        "recipient_phone": recipient_phone,
    }

    session.context_json = json.dumps(
        ctx,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    db.flush()

    _, url = continuation_url(
        session.id
    )

    text = (
        "CUP - Invio documenti\n\n"
        f"Durante la chiamata puoi inviare {document_label} "
        "aprendo questo link sicuro:\n"
        f"{url}\n\n"
        "Puoi fotografare il documento oppure allegare un file."
    )

    delivery = {
        "ok": False,
        "detail": "",
    }

    if channel == "sms":
        result = send_continuation_sms(
            recipient_phone,
            url,
        )

        delivery = {
            "ok": bool(
                result.get("ok", False)
            ),
            "sent": bool(
                result.get("sent", False)
            ),
            "mode": result.get("mode"),
            "detail": (
                result.get("message")
                or result.get("reason")
                or result.get("mode")
                or ""
            ),
        }

        if not delivery["ok"]:
            raise HTTPException(
                status_code=502,
                detail=(
                    delivery["detail"]
                    or "Invio SMS non riuscito"
                ),
            )

        add_channel_link(
            db,
            session.id,
            "sms",
            phone,
            phone,
            {
                "continuation": True,
                "document_exchange": True,
                "call_id": call.id,
            },
        )

    elif channel == "whatsapp":
        try:
            ok, detail = _send_whatsapp(
                recipient_phone,
                text,
            )
        except Exception as exc:
            ok = False
            detail = str(exc)

        if not ok:
            raise HTTPException(
                status_code=502,
                detail=(
                    detail
                    or "Invio WhatsApp non riuscito"
                ),
            )

        delivery = {
            "ok": True,
            "sent": True,
            "mode": "whatsapp",
            "detail": detail,
        }

        add_channel_link(
            db,
            session.id,
            "whatsapp",
            phone,
            phone,
            {
                "continuation": True,
                "document_exchange": True,
                "call_id": call.id,
            },
        )

    elif channel == "telegram":
        # Doppio controllo server-side:
        # non e' sufficiente che il pulsante sia nascosto.
        telegram_chat_id = info[
            "telegram_chat_id"
        ]

        if (
            not patient
            or not telegram_chat_id
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Telegram non associato "
                    "all'anagrafica del paziente"
                ),
            )

        try:
            ok, detail = _send_telegram(
                str(telegram_chat_id),
                text,
            )
        except Exception as exc:
            ok = False
            detail = str(exc)

        if not ok:
            raise HTTPException(
                status_code=502,
                detail=(
                    detail
                    or "Invio Telegram non riuscito"
                ),
            )

        delivery = {
            "ok": True,
            "sent": True,
            "mode": "telegram",
            "detail": detail,
        }

        add_channel_link(
            db,
            session.id,
            "telegram",
            str(telegram_chat_id),
            display_name,
            {
                "continuation": True,
                "document_exchange": True,
                "call_id": call.id,
            },
        )

    db.add(
        HandoffEvent(
            session_id=session.id,
            event="document_link_sent",
            from_owner="operator",
            to_owner="customer",
            operator_id=getattr(
                user,
                "id",
                None,
            ),
            call_id=call.id,
            reason=(
                "Richiesta documento via "
                + channel
                + " · "
                + requested_type
            ),
        )
    )

    db.add(
        ChatMessage(
            session_id=session.id,
            role="system",
            content=(
                "Operatore: richiesta di "
                f"{document_label} inviata via "
                f"{channel.upper()}."
            ),
        )
    )

    # Se la chiamata e' stata riconciliata tramite telefono
    # manteniamo il collegamento deterministico.
    if (
        patient
        and not getattr(
            call,
            "patient_id",
            None,
        )
    ):
        call.patient_id = patient.id

    db.commit()

    return {
        "ok": True,
        "call_id": call.id,
        "session_id": session.id,
        "channel": channel,
        "document_type": requested_type,
        "url": url,
        "delivery": delivery,
    }


@router.get(
    "/calls/{call_id}/document-exchange"
)
def omnia_document_exchange_status(
    call_id: int,
    session_id: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(
        require_role(
            "admin",
            "operator",
        )
    ),
):
    from app.models.call import Call

    call = db.query(Call).filter(
        Call.id == call_id
    ).first()

    if not call:
        raise HTTPException(
            status_code=404,
            detail="Chiamata non trovata",
        )

    session = _omnia_doc_find_session(
        db,
        call_id,
        session_id,
    )

    if not session:
        return {
            "ok": True,
            "call_id": call_id,
            "session_id": None,
            "attachments": [],
        }

    attachments = []

    for attachment in (
        session.attachments or []
    ):
        attachments.append({
            "id": attachment.id,
            "filename": attachment.original_filename,
            "mime_type": attachment.mime_type,
            "size_bytes": attachment.size_bytes,
            "created_at": attachment.created_at,
            "url": (
                "/api/chatbot/sessions/"
                + session.id
                + "/attachments/"
                + str(attachment.id)
            ),
        })

    return {
        "ok": True,
        "call_id": call_id,
        "session_id": session.id,
        "patient_id": session.patient_id,
        "attachments": attachments,
    }


# /OMNIA_LIVE_DOC_EXCHANGE_V1


@router.post("/sessions/{session_id}/sms-link")
def send_sms_link(session_id: str, payload: SmsLinkRequest, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Conversazione non trovata")
    phone = (payload.phone or "").strip()
    if not phone:
        links = links_for_session(db, session_id)
        preferred = next((x.external_id for x in links if x.channel == "phone" and x.external_id), None)
        phone = preferred or next((x.external_id for x in links if x.channel == "whatsapp" and x.external_id), None) or (session.sender_id or "")
    if not phone:
        raise HTTPException(status_code=400, detail="Numero telefonico non disponibile")
    _, url = continuation_url(session.id)
    result = send_continuation_sms(phone, url)
    add_channel_link(db, session.id, "sms", phone, phone, {"continuation": True})
    db.add(HandoffEvent(
        session_id=session.id, event="sms_sent", from_owner="operator", to_owner="customer", operator_id=user.id,
        reason="Link sicuro per continuazione web e caricamento documenti" + (" (gateway)" if result.get("sent") else " (mock)"),
    ))
    db.add(ChatMessage(session_id=session.id, role="system", content=f"Link di continuazione web generato e associato al numero {phone}."))
    db.commit()
    return {"ok": result.get("ok", False), "sent": result.get("sent", False), "mode": result.get("mode"), "phone": phone, "url": url, "gateway": result}


@router.get("/continue/{token}")
def continue_from_token(token: str, db: Session = Depends(get_db)):
    try:
        session_id = resolve_continuation_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session or session.status == "closed":
        raise HTTPException(status_code=404, detail="Sessione non disponibile")
    web_external_id = f"continuation:{session.id}"
    existing = db.query(ConversationChannel).filter(
        ConversationChannel.channel == "web", ConversationChannel.external_id == web_external_id
    ).first()
    if not existing:
        add_channel_link(db, session.id, "web", web_external_id, "Pagina web da SMS", {"source": "sms"})
        db.add(HandoffEvent(session_id=session.id, event="web_opened", from_owner="customer", to_owner=_owner(session), reason="Cliente entrato nella sessione web dal link SMS"))
        db.add(ChatMessage(session_id=session.id, role="system", content="Il cliente ha aperto il link SMS ed è entrato nella sessione web."))
        db.commit()
    return {"ok": True, "session_id": session.id, "status": session.status}


@router.post("/sessions/{session_id}/handoff")
async def request_handoff(session_id: str, payload: HandoffRequest, background: BackgroundTasks, db: Session = Depends(get_db), user=Depends(require_operator_channel("chat"))):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Conversazione non trovata")

    require_live(db, session)

    handoff, created = handoff_service.create_request(db, session, payload.reason, source=session.channel or "chat")
    if handoff_service.available_operators(db, "chat"):
        handoff_service.mark_ringing(db, handoff)
    db.commit()
    if chatwoot_service.enabled() and settings.CHATWOOT_AUTO_SYNC_HANDOFF:
        try:
            chatwoot_service.ensure_binding(db, session)
            chatwoot_service.set_status(db, session, "open")
            db.commit()
        except Exception:
            pass
    return {"ok": True, "status": session.status, "handoff_id": handoff.id, "created": created}


@router.post("/sessions/{session_id}/owner")
def set_owner(session_id: str, payload: OwnerRequest, db: Session = Depends(get_db), user=Depends(require_operator_channel("chat"))):
    if payload.owner not in {"llm", "operator"}:
        raise HTTPException(status_code=400, detail="Owner non valido")
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Conversazione non trovata")

    require_live(db, session)

    previous = _owner(session)
    session.status = "handoff" if payload.owner == "operator" else "bot"
    event = "accepted" if payload.owner == "operator" else "returned_to_llm"
    db.add(HandoffEvent(session_id=session.id, event=event, from_owner=previous, to_owner=payload.owner, operator_id=user.id))
    db.add(ChatMessage(session_id=session.id, role="system", content=f"Gestione conversazione: {payload.owner}."))
    if chatwoot_service.enabled():
        try:
            chatwoot_service.set_status(db, session, "open" if payload.owner == "operator" else "pending")
        except Exception:
            pass
    db.commit()
    return {"ok": True, "owner": payload.owner, "status": session.status}



# ============================================================
# OMNIA_OPERATOR_PATIENT_CONTEXT_V11
# Contesto paziente per Omnia Console.
# Endpoint read-only riservato a admin/operator.
# ============================================================

@router.get("/patients/{patient_id}/operator-context")
def omnia_operator_patient_context(
    patient_id: int,
    db: Session = Depends(get_db),
    user=Depends(
        require_role(
            "admin",
            "operator",
        )
    ),
):
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text as sa_text

    inspector = sa_inspect(db.bind)
    tables = set(inspector.get_table_names())

    result = {
        "ok": True,
        "patient_id": patient_id,
        "bookings": [],
        "documents": [],
        "pending_count": 0,
    }

    # --------------------------------------------------------
    # PRENOTAZIONI
    # --------------------------------------------------------

    if "bookings" in tables:
        try:
            rows = (
                db.execute(
                    sa_text("""
                        SELECT *
                        FROM bookings
                        WHERE patient_id = :patient_id
                        ORDER BY scheduled_at DESC
                        LIMIT 8
                    """),
                    {"patient_id": patient_id},
                )
                .mappings()
                .all()
            )

            for row in rows:
                data = dict(row)

                status = str(
                    data.get("status")
                    or ""
                ).lower()

                if status in {
                    "pending",
                    "waiting",
                    "requested",
                    "hold",
                    "held",
                }:
                    result["pending_count"] += 1

                result["bookings"].append({
                    "id": data.get("id"),
                    "service_name": (
                        data.get("service_name")
                        or data.get("service")
                        or data.get("visit_name")
                        or "Prestazione"
                    ),
                    "scheduled_at": data.get("scheduled_at"),
                    "status": data.get("status"),
                    "regime": (
                        data.get("care_regime")
                        or data.get("regime")
                    ),
                    "price_cents": (
                        data.get("quoted_price_cents")
                        or data.get("price_cents")
                    ),
                    "agenda_id": data.get("agenda_id"),
                })

        except Exception:
            logger.exception(
                "Omnia V11: lettura bookings fallita "
                "patient_id=%s",
                patient_id,
            )

    # --------------------------------------------------------
    # DOCUMENTI PAZIENTE
    # --------------------------------------------------------

    if "patient_documents" in tables:
        try:
            rows = (
                db.execute(
                    sa_text("""
                        SELECT *
                        FROM patient_documents
                        WHERE patient_id = :patient_id
                        ORDER BY created_at DESC
                        LIMIT 8
                    """),
                    {"patient_id": patient_id},
                )
                .mappings()
                .all()
            )

            for row in rows:
                data = dict(row)

                result["documents"].append({
                    "id": data.get("id"),
                    "title": (
                        data.get("title")
                        or data.get("filename")
                        or "Documento"
                    ),
                    "filename": data.get("filename"),
                    "category": data.get("category"),
                    "status": data.get("status"),
                    "created_at": data.get("created_at"),
                })

        except Exception:
            logger.exception(
                "Omnia V11: lettura patient_documents "
                "fallita patient_id=%s",
                patient_id,
            )

    return result

# /OMNIA_OPERATOR_PATIENT_CONTEXT_V11


