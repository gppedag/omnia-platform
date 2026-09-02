from __future__ import annotations
import base64
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from jose import JWTError, jwt
from sqlalchemy.orm import joinedload

from app.config import settings
from app.models.commerce import SignatureRequest
from app.models.patient import Patient
from app.services.customer_delivery import send_patient_message


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_dir():
    os.makedirs(settings.SIGNATURE_UPLOAD_DIR, exist_ok=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_token(request_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(request_id), "purpose": "document_signature", "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=max(1, settings.SIGNATURE_LINK_TTL_HOURS))).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def resolve_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Link firma non valido o scaduto") from exc
    if payload.get("purpose") != "document_signature":
        raise ValueError("Link firma non valido")
    return int(payload["sub"])


def public_url(request_id: int) -> str:
    token = quote(create_token(request_id), safe="")
    base = settings.CUP_PUBLIC_BASE_URL.rstrip("/")
    path = f"/signature.html?token={token}"
    return base + path if base else path


def send_request(db, row: SignatureRequest) -> list[dict]:
    patient = db.query(Patient).options(joinedload(Patient.user)).filter(Patient.id == row.patient_id).first()
    if not patient:
        raise ValueError("Paziente non trovato")
    text = settings.SIGNATURE_REQUEST_TEMPLATE.format(title=row.title, signature_url=public_url(row.id))
    results = send_patient_message(patient, text, row.channels, settings.SIGNATURE_CHANNELS, subject="Documento da firmare · CUP")
    if any(x["ok"] for x in results):
        row.status = "sent" if row.status == "pending" else row.status
        row.sent_at = _utcnow()
    db.commit(); db.refresh(row)
    return results


def save_signature_image(request_id: int, data_url: str) -> tuple[str, str]:
    ensure_dir()
    match = re.match(r"^data:image/png;base64,(.+)$", data_url or "", flags=re.S)
    if not match:
        raise ValueError("Firma grafica non valida")
    raw = base64.b64decode(match.group(1), validate=True)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Firma grafica troppo grande")
    digest = sha256_bytes(raw)
    path = os.path.join(settings.SIGNATURE_UPLOAD_DIR, f"signature-{request_id}-{digest[:12]}.png")
    with open(path, "wb") as fh:
        fh.write(raw)
    return path, digest


def audit_payload(row: SignatureRequest) -> dict:
    return {
        "request_id": row.id,
        "title": row.title,
        "patient_id": row.patient_id,
        "booking_id": row.booking_id,
        "status": row.status,
        "original_filename": row.original_filename,
        "document_sha256": row.document_sha256,
        "signer_name": row.signer_name,
        "signature_sha256": row.signature_sha256,
        "signed_at": row.signed_at.isoformat() if row.signed_at else None,
        "signed_ip": row.signed_ip,
        "signed_user_agent": row.signed_user_agent,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
