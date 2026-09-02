from __future__ import annotations
import logging
from pathlib import Path
from urllib.parse import urljoin
import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.chat import ChatSession, ChatMessage, ChatAttachment
from app.models.chatwoot import ChatwootBinding
from app.models.omnichannel import ConversationChannel

logger = logging.getLogger("chatwoot_service")


def enabled() -> bool:
    return bool(
        settings.CHATWOOT_ENABLED
        and settings.CHATWOOT_BASE_URL
        and settings.CHATWOOT_ACCOUNT_ID
        and settings.CHATWOOT_API_TOKEN
        and settings.CHATWOOT_INBOX_IDENTIFIER
    )


def _base() -> str:
    return settings.CHATWOOT_BASE_URL.rstrip("/") + "/"


def _headers() -> dict:
    return {"api_access_token": settings.CHATWOOT_API_TOKEN, "Content-Type": "application/json"}


def _client() -> httpx.Client:
    return httpx.Client(timeout=settings.CHATWOOT_TIMEOUT_SECONDS, follow_redirects=True)


def _display_name(db: Session, session: ChatSession) -> str:
    link = db.query(ConversationChannel).filter(ConversationChannel.session_id == session.id).order_by(ConversationChannel.id).first()
    return (link.display_name if link and link.display_name else None) or session.sender_id or f"CUP {session.id[:8]}"


def _identifier(session: ChatSession) -> str:
    # Una conversazione Chatwoot per journey CUP. Il patient_id e un attributo separato e non viene usato come unico identificatore.
    return f"cup:journey:{session.journey_id or session.id}"


def ensure_binding(db: Session, session: ChatSession) -> ChatwootBinding | None:
    if not enabled():
        return None
    existing = db.query(ChatwootBinding).filter(ChatwootBinding.session_id == session.id).first()
    if existing:
        return existing

    inbox_identifier = settings.CHATWOOT_INBOX_IDENTIFIER
    identifier = _identifier(session)
    contact_url = urljoin(_base(), f"public/api/v1/inboxes/{inbox_identifier}/contacts")
    payload = {
        "identifier": identifier,
        "name": _display_name(db, session),
        "phone_number": (
            "+" + "".join(ch for ch in session.sender_id if ch.isdigit())
            if session.channel in {"whatsapp", "phone"} and session.sender_id
            else None
        ),
        "custom_attributes": {"cup_session_id": session.id, "cup_journey_id": session.journey_id or session.id, "cup_patient_id": session.patient_id, "cup_channel": session.channel},
    }
    payload = {k: v for k, v in payload.items() if v not in (None, "")}
    with _client() as client:
        r = client.post(contact_url, json=payload)
        if r.status_code not in (200, 201):
            logger.error("Chatwoot contact create failed: %s %s", r.status_code, r.text[:500])
            return None
        contact = r.json()
        source_id = contact.get("source_id") or contact.get("identifier")
        contact_id = contact.get("id")
        conv_url = urljoin(_base(), f"public/api/v1/inboxes/{inbox_identifier}/contacts/{source_id}/conversations")
        cr = client.post(conv_url, json={"custom_attributes": {"cup_session_id": session.id, "cup_journey_id": session.journey_id or session.id, "cup_patient_id": session.patient_id, "cup_owner": "llm"}})
        if cr.status_code not in (200, 201):
            logger.error("Chatwoot conversation create failed: %s %s", cr.status_code, cr.text[:500])
            return None
        conv = cr.json()

    if settings.CHATWOOT_TEAM_ID:
        assign_url = urljoin(_base(), f"api/v1/accounts/{settings.CHATWOOT_ACCOUNT_ID}/conversations/{conv['id']}/assignments")
        try:
            with _client() as client:
                client.post(assign_url, headers=_headers(), json={"team_id": settings.CHATWOOT_TEAM_ID})
        except Exception:
            logger.exception("Chatwoot team assignment failed")

    binding = ChatwootBinding(
        session_id=session.id,
        conversation_id=int(conv["id"]),
        contact_id=int(contact_id) if contact_id is not None else None,
        contact_source_id=str(source_id),
        inbox_identifier=inbox_identifier,
        status=str(conv.get("status") or "open"),
    )
    db.add(binding)
    db.flush()
    return binding


def push_message(db: Session, session: ChatSession, content: str, sender: str, private: bool = False) -> dict:
    if not enabled() or not content:
        return {"ok": False, "skipped": True}
    binding = ensure_binding(db, session)
    if not binding:
        return {"ok": False, "error": "binding unavailable"}
    message_type = "incoming" if sender == "user" else "outgoing"
    payload = {
        "content": content,
        "message_type": message_type,
        "private": private,
        "content_type": "text",
        "content_attributes": {
            "cup_origin": "cup-system",
            "cup_sender": sender,
            "cup_session_id": session.id,
            "cup_journey_id": session.journey_id or session.id,
            "cup_patient_id": session.patient_id,
        },
    }
    url = urljoin(_base(), f"api/v1/accounts/{settings.CHATWOOT_ACCOUNT_ID}/conversations/{binding.conversation_id}/messages")
    with _client() as client:
        r = client.post(url, headers=_headers(), json=payload)
    return {"ok": r.is_success, "status_code": r.status_code, "body": r.text[:500]}


def push_attachment_note(db: Session, session: ChatSession, attachment: ChatAttachment) -> dict:
    # CHATWOOT_NATIVE_ATTACHMENT_V1
    if not enabled():
        return {"ok": False, "skipped": True}

    binding = ensure_binding(db, session)
    if not binding:
        return {"ok": False, "error": "binding unavailable"}

    file_path = (
        Path(settings.CHAT_UPLOAD_DIR)
        / session.id
        / attachment.stored_filename
    )

    endpoint = urljoin(
        _base(),
        f"api/v1/accounts/{settings.CHATWOOT_ACCOUNT_ID}/"
        f"conversations/{binding.conversation_id}/messages"
    )

    text = (
        f"Documento CUP: {attachment.original_filename}"
    )

    # Prima scelta: attachment nativo Chatwoot.
    if file_path.exists():
        try:
            with file_path.open("rb") as fh:
                files = {
                    "attachments[]": (
                        attachment.original_filename,
                        fh,
                        attachment.mime_type or "application/octet-stream",
                    )
                }

                data = {
                    "content": text,
                    "message_type": "incoming",
                    "private": "false",
                    "content_type": "text",
                }

                headers = {
                    "api_access_token":
                        settings.CHATWOOT_API_TOKEN
                }

                with _client() as client:
                    r = client.post(
                        endpoint,
                        headers=headers,
                        data=data,
                        files=files,
                    )

                if r.is_success:
                    return {
                        "ok": True,
                        "native_attachment": True,
                        "status_code": r.status_code,
                        "conversation_id":
                            binding.conversation_id,
                        "body": r.text[:500],
                    }

                logger.warning(
                    "Chatwoot native attachment failed: %s %s",
                    r.status_code,
                    r.text[:500],
                )

        except Exception:
            logger.exception(
                "Chatwoot native attachment upload failed"
            )

    # Fallback: nota privata con link CUP.
    base = settings.CUP_PUBLIC_BASE_URL.rstrip("/")
    url = (
        f"{base}/api/chatbot/web/{session.id}/"
        f"attachments/{attachment.id}"
        if base else ""
    )

    fallback_text = (
        f"Documento CUP: {attachment.original_filename} "
        f"({attachment.mime_type}, "
        f"{attachment.size_bytes} byte)"
    )

    if url:
        fallback_text += f"\n{url}"

    result = push_message(
        db,
        session,
        fallback_text,
        "system",
        private=True,
    )

    result["native_attachment"] = False
    result["fallback"] = True
    return result


def push_history(db: Session, session: ChatSession) -> dict:
    binding = ensure_binding(db, session)
    if not binding:
        return {"ok": False, "error": "binding unavailable"}
    pushed = 0
    for m in session.messages:
        result = push_message(db, session, m.content, m.role if m.role in {"user", "assistant", "operator"} else "system", private=(m.role == "system"))
        if result.get("ok"):
            pushed += 1
    for a in session.attachments:
        if push_attachment_note(db, session, a).get("ok"):
            pushed += 1
    return {"ok": True, "pushed": pushed, "conversation_id": binding.conversation_id}


def set_status(db: Session, session: ChatSession, status: str) -> dict:
    binding = ensure_binding(db, session)
    if not binding:
        return {"ok": False, "error": "binding unavailable"}
    url = urljoin(_base(), f"api/v1/accounts/{settings.CHATWOOT_ACCOUNT_ID}/conversations/{binding.conversation_id}/toggle_status")
    with _client() as client:
        r = client.post(url, headers=_headers(), json={"status": status})
    if r.is_success:
        binding.status = status
    return {"ok": r.is_success, "status_code": r.status_code, "body": r.text[:500]}


def find_binding(db: Session, conversation_id: int) -> ChatwootBinding | None:
    return db.query(ChatwootBinding).filter(ChatwootBinding.conversation_id == conversation_id).first()


def create_webhook(callback_url: str) -> dict:
    if not enabled():
        return {"ok": False, "error": "Chatwoot non configurato"}
    url = urljoin(_base(), f"api/v1/accounts/{settings.CHATWOOT_ACCOUNT_ID}/webhooks")
    payload = {
        "url": callback_url,
        "name": "CUP System v1.0.30",
        "subscriptions": ["message_created", "conversation_status_changed", "conversation_updated"],
    }
    with _client() as client:
        r = client.post(url, headers=_headers(), json=payload)
    return {"ok": r.is_success, "status_code": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:1000]}
