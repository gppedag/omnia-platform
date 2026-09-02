from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from jose import JWTError, jwt

from app.config import settings


def create_continuation_token(session_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": session_id,
        "purpose": "cup_web_continuation",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.CONTINUATION_TOKEN_TTL_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def resolve_continuation_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Token di continuazione non valido o scaduto") from exc
    if payload.get("purpose") != "cup_web_continuation" or not payload.get("sub"):
        raise ValueError("Token di continuazione non valido")
    return str(payload["sub"])


def continuation_url(session_id: str) -> tuple[str, str]:
    token = create_continuation_token(session_id)
    base = settings.CUP_PUBLIC_BASE_URL.rstrip("/")
    path = f"/chatbot.html?journey_token={quote(token, safe='')}"
    return token, (base + path if base else path)


def send_continuation_sms(phone: str, url: str) -> dict:
    text = (
        "CUP: continua la richiesta e carica i documenti dal link sicuro: "
        f"{url} Il link scade tra {settings.CONTINUATION_TOKEN_TTL_MINUTES} minuti."
    )
    if not settings.SMS_GATEWAY_URL:
        return {"ok": True, "sent": False, "mode": "mock", "reason": "sms_gateway_not_configured", "text": text}
    headers = {"Content-Type": "application/json"}
    if settings.SMS_GATEWAY_TOKEN:
        headers["Authorization"] = f"Bearer {settings.SMS_GATEWAY_TOKEN}"
    try:
        response = httpx.post(
            settings.SMS_GATEWAY_URL,
            headers=headers,
            json={"to": phone, "text": text, "sender": settings.SMS_SENDER},
            timeout=settings.SMS_TIMEOUT_SECONDS,
        )
        return {
            "ok": response.is_success,
            "sent": response.is_success,
            "mode": "gateway",
            "status_code": response.status_code,
            "response": response.text[:500],
        }
    except Exception as exc:
        return {"ok": False, "sent": False, "mode": "gateway", "error": str(exc)}
