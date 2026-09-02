from datetime import datetime
import json
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from app.auth import require_role
from app.config import settings
from app.db.database import get_db
from app.models.commerce import PaymentRequest
from app.models.patient import Patient
from app.models.booking import Booking
from app.services import payment_service

router = APIRouter(prefix="/api/payments", tags=["payments"])

class PaymentCreate(BaseModel):
    patient_id: int
    booking_id: int | None = None
    description: str = Field(min_length=2, max_length=255)
    amount: float = Field(gt=0)
    currency: str = "EUR"
    channels: str | None = None
    due_at: datetime | None = None
    send_now: bool = True

class PaymentStatus(BaseModel):
    status: str


def serialize(row: PaymentRequest, db: Session):
    p = db.query(Patient).options(joinedload(Patient.user)).filter(Patient.id == row.patient_id).first()
    return {
        "id": row.id, "patient_id": row.patient_id, "patient_name": p.user.full_name if p and p.user else None,
        "booking_id": row.booking_id, "description": row.description, "amount_cents": row.amount_cents,
        "amount": round(row.amount_cents / 100, 2), "currency": row.currency, "provider": row.provider,
        "status": row.status, "checkout_url": row.checkout_url, "external_reference": row.external_reference,
        "channels": row.channels, "due_at": row.due_at, "sent_at": row.sent_at, "paid_at": row.paid_at,
        "created_at": row.created_at, "payment_url": payment_service.public_url(row.id),
    }

@router.get("")
def list_payments(db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    return [serialize(x, db) for x in db.query(PaymentRequest).order_by(PaymentRequest.created_at.desc()).limit(300).all()]

@router.post("", status_code=201)
def create_payment(payload: PaymentCreate, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    if not settings.PAYMENTS_ENABLED:
        raise HTTPException(409, "Pagamenti disabilitati")
    if not db.query(Patient).filter(Patient.id == payload.patient_id).first():
        raise HTTPException(404, "Paziente non trovato")
    if payload.booking_id and not db.query(Booking).filter(Booking.id == payload.booking_id, Booking.patient_id == payload.patient_id).first():
        raise HTTPException(400, "Prenotazione non coerente con il paziente")
    row = PaymentRequest(patient_id=payload.patient_id, booking_id=payload.booking_id, created_by=user.id,
                         description=payload.description, amount_cents=int(round(payload.amount * 100)),
                         currency=(payload.currency or settings.PAYMENT_DEFAULT_CURRENCY).upper(), channels=payload.channels,
                         due_at=payload.due_at, provider=(settings.PAYMENT_PROVIDER or "manual").lower())
    db.add(row); db.commit(); db.refresh(row)
    try:
        checkout, ref, detail = payment_service.create_checkout(row)
    except Exception as exc:
        checkout, ref, detail = None, None, str(exc)
    row.checkout_url = checkout; row.external_reference = ref; row.provider_response = detail
    if row.provider in {"stripe", "external"} and not checkout:
        row.status = "failed"
    db.commit(); db.refresh(row)
    if payload.send_now and row.status != "failed":
        payment_service.send_request(db, row)
    return serialize(row, db)

@router.post("/{payment_id}/send")
def send_payment(payment_id: int, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    row = db.get(PaymentRequest, payment_id)
    if not row: raise HTTPException(404, "Richiesta pagamento non trovata")
    return {"ok": True, "results": payment_service.send_request(db, row), "payment": serialize(row, db)}

@router.patch("/{payment_id}/status")
def set_payment_status(payment_id: int, payload: PaymentStatus, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    if payload.status not in {"pending", "sent", "paid", "cancelled", "failed"}:
        raise HTTPException(400, "Stato non valido")
    row = db.get(PaymentRequest, payment_id)
    if not row: raise HTTPException(404, "Richiesta pagamento non trovata")
    row.status = payload.status
    if payload.status == "paid" and not row.paid_at: row.paid_at = datetime.utcnow()
    db.commit(); db.refresh(row)
    return serialize(row, db)

@router.get("/public/{token}")
def public_payment(token: str, db: Session = Depends(get_db)):
    try: pid = payment_service.resolve_token(token)
    except ValueError as exc: raise HTTPException(400, str(exc))
    row = db.get(PaymentRequest, pid)
    if not row: raise HTTPException(404, "Pagamento non trovato")
    p = db.query(Patient).options(joinedload(Patient.user)).filter(Patient.id == row.patient_id).first()
    return {"id": row.id, "description": row.description, "amount": round(row.amount_cents/100,2), "currency": row.currency,
            "status": row.status, "provider": row.provider, "checkout_url": row.checkout_url,
            "patient_name": p.user.full_name if p and p.user else None, "due_at": row.due_at}

@router.post("/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not payment_service.verify_stripe_signature(raw, request.headers.get("stripe-signature", "")):
        raise HTTPException(401, "Firma webhook Stripe non valida")
    event = json.loads(raw.decode("utf-8"))
    if event.get("type") in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        obj = event.get("data", {}).get("object", {})
        pid = (obj.get("metadata") or {}).get("payment_id")
        if pid:
            row = db.get(PaymentRequest, int(pid))
            if row:
                row.status = "paid"; row.paid_at = datetime.utcnow(); row.external_reference = obj.get("id") or row.external_reference
                db.commit()
    return {"received": True}
