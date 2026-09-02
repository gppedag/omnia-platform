import json
import os
import uuid
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from app.auth import require_role
from app.config import settings
from app.db.database import get_db
from app.models.commerce import SignatureRequest
from app.models.patient import Patient
from app.models.booking import Booking
from app.services import signature_service

router = APIRouter(prefix="/api/signatures", tags=["signatures"])

class SignPayload(BaseModel):
    signer_name: str = Field(min_length=2, max_length=255)
    accepted: bool
    signature_data: str

class DeclinePayload(BaseModel):
    reason: str | None = None


def serialize(row: SignatureRequest, db: Session):
    p = db.query(Patient).options(joinedload(Patient.user)).filter(Patient.id == row.patient_id).first()
    return {"id": row.id, "patient_id": row.patient_id, "patient_name": p.user.full_name if p and p.user else None,
            "booking_id": row.booking_id, "title": row.title, "message": row.message, "original_filename": row.original_filename,
            "document_sha256": row.document_sha256, "status": row.status, "channels": row.channels,
            "signer_name": row.signer_name, "sent_at": row.sent_at, "viewed_at": row.viewed_at, "signed_at": row.signed_at,
            "declined_at": row.declined_at, "expires_at": row.expires_at, "created_at": row.created_at,
            "signature_url": signature_service.public_url(row.id)}

@router.get("")
def list_requests(db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    return [serialize(x, db) for x in db.query(SignatureRequest).order_by(SignatureRequest.created_at.desc()).limit(300).all()]

@router.post("", status_code=201)
async def create_request(patient_id: int = Form(...), title: str = Form(...), booking_id: int | None = Form(default=None),
                         message: str | None = Form(default=None), channels: str | None = Form(default=None),
                         send_now: bool = Form(default=True), document: UploadFile = File(...),
                         db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    if not settings.SIGNATURES_ENABLED:
        raise HTTPException(409, "Firma documentale disabilitata")
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient: raise HTTPException(404, "Paziente non trovato")
    if booking_id and not db.query(Booking).filter(Booking.id == booking_id, Booking.patient_id == patient_id).first():
        raise HTTPException(400, "Prenotazione non coerente con il paziente")
    name = document.filename or "documento.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Per la firma interna è richiesto un documento PDF")
    raw = await document.read()
    if not raw or len(raw) > settings.SIGNATURE_MAX_FILE_BYTES:
        raise HTTPException(400, "Documento vuoto o troppo grande")
    signature_service.ensure_dir()
    stored = os.path.join(settings.SIGNATURE_UPLOAD_DIR, f"document-{uuid.uuid4().hex}.pdf")
    with open(stored, "wb") as fh: fh.write(raw)
    row = SignatureRequest(patient_id=patient_id, booking_id=booking_id, created_by=user.id, title=title.strip(),
                           message=message, original_filename=name, stored_path=stored,
                           document_sha256=signature_service.sha256_bytes(raw), channels=channels,
                           expires_at=datetime.utcnow() + timedelta(hours=settings.SIGNATURE_LINK_TTL_HOURS))
    db.add(row); db.commit(); db.refresh(row)
    if send_now: signature_service.send_request(db, row)
    return serialize(row, db)

@router.post("/{request_id}/send")
def resend(request_id: int, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    row = db.get(SignatureRequest, request_id)
    if not row: raise HTTPException(404, "Richiesta firma non trovata")
    return {"ok": True, "results": signature_service.send_request(db, row), "request": serialize(row, db)}

@router.get("/{request_id}/audit")
def audit(request_id: int, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    row = db.get(SignatureRequest, request_id)
    if not row: raise HTTPException(404, "Richiesta firma non trovata")
    return signature_service.audit_payload(row)

@router.get("/public/{token}")
def public_info(token: str, db: Session = Depends(get_db)):
    try: rid = signature_service.resolve_token(token)
    except ValueError as exc: raise HTTPException(400, str(exc))
    row = db.get(SignatureRequest, rid)
    if not row: raise HTTPException(404, "Richiesta firma non trovata")
    if row.expires_at and row.expires_at < datetime.utcnow() and row.status not in {"signed", "declined"}:
        row.status = "expired"; db.commit()
    if row.status in {"pending", "sent"}:
        row.status = "viewed"; row.viewed_at = datetime.utcnow(); db.commit(); db.refresh(row)
    p = db.query(Patient).options(joinedload(Patient.user)).filter(Patient.id == row.patient_id).first()
    return {"id": row.id, "title": row.title, "message": row.message, "patient_name": p.user.full_name if p and p.user else None,
            "status": row.status, "document_sha256": row.document_sha256, "expires_at": row.expires_at,
            "document_url": f"/api/signatures/public/{token}/document"}

@router.get("/public/{token}/document")
def public_document(token: str, db: Session = Depends(get_db)):
    try: rid = signature_service.resolve_token(token)
    except ValueError as exc: raise HTTPException(400, str(exc))
    row = db.get(SignatureRequest, rid)
    if not row or not os.path.exists(row.stored_path): raise HTTPException(404, "Documento non trovato")
    return FileResponse(row.stored_path, media_type="application/pdf", filename=row.original_filename)

@router.post("/public/{token}/sign")
def sign(token: str, payload: SignPayload, request: Request, db: Session = Depends(get_db)):
    try: rid = signature_service.resolve_token(token)
    except ValueError as exc: raise HTTPException(400, str(exc))
    row = db.query(SignatureRequest).filter(SignatureRequest.id == rid).with_for_update().first()
    if not row: raise HTTPException(404, "Richiesta firma non trovata")
    if row.status == "signed": return {"ok": True, "status": "signed"}
    if row.status in {"declined", "expired"}: raise HTTPException(409, "Richiesta non più firmabile")
    if row.expires_at and row.expires_at < datetime.utcnow():
        row.status = "expired"; db.commit(); raise HTTPException(410, "Richiesta firma scaduta")
    if not payload.accepted: raise HTTPException(400, "È necessario accettare il contenuto del documento")
    path, digest = signature_service.save_signature_image(row.id, payload.signature_data)
    row.signature_png_path = path; row.signature_sha256 = digest; row.signer_name = payload.signer_name.strip()
    row.signed_ip = request.client.host if request.client else None; row.signed_user_agent = request.headers.get("user-agent", "")[:1000]
    row.signed_at = datetime.utcnow(); row.status = "signed"
    db.commit(); db.refresh(row)
    return {"ok": True, "status": row.status, "signed_at": row.signed_at}

@router.post("/public/{token}/decline")
def decline(token: str, payload: DeclinePayload, db: Session = Depends(get_db)):
    try: rid = signature_service.resolve_token(token)
    except ValueError as exc: raise HTTPException(400, str(exc))
    row = db.query(SignatureRequest).filter(SignatureRequest.id == rid).with_for_update().first()
    if not row: raise HTTPException(404, "Richiesta firma non trovata")
    if row.status == "signed": raise HTTPException(409, "Documento già firmato")
    row.status = "declined"; row.declined_reason = payload.reason; row.declined_at = datetime.utcnow(); db.commit()
    return {"ok": True, "status": row.status}
