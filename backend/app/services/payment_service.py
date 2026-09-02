from __future__ import annotations
import hmac
import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import httpx
from jose import JWTError, jwt
from sqlalchemy.orm import joinedload

from app.config import settings
from app.models.commerce import PaymentRequest
from app.models.patient import Patient
from app.services.customer_delivery import send_patient_message


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_token(payment_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(payment_id), "purpose": "payment_request", "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=max(1, settings.PAYMENT_LINK_TTL_HOURS))).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def resolve_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Link di pagamento non valido o scaduto") from exc
    if payload.get("purpose") != "payment_request":
        raise ValueError("Link di pagamento non valido")
    return int(payload["sub"])


def public_url(payment_id: int) -> str:
    token = quote(create_token(payment_id), safe="")
    base = settings.CUP_PUBLIC_BASE_URL.rstrip("/")
    path = f"/payment.html?token={token}"
    return base + path if base else path


def create_checkout(payment: PaymentRequest) -> tuple[str | None, str | None, str]:
    provider = (settings.PAYMENT_PROVIDER or "manual").strip().lower()
    payment.provider = provider
    if provider == "stripe":
        if not settings.STRIPE_SECRET_KEY:
            return None, None, "Stripe non configurato"
        success = settings.PAYMENT_SUCCESS_URL or public_url(payment.id)
        cancel = settings.PAYMENT_CANCEL_URL or public_url(payment.id)
        data = {
            "mode": "payment",
            "success_url": success,
            "cancel_url": cancel,
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": payment.currency.lower(),
            "line_items[0][price_data][unit_amount]": str(payment.amount_cents),
            "line_items[0][price_data][product_data][name]": payment.description,
            "metadata[payment_id]": str(payment.id),
        }
        r = httpx.post("https://api.stripe.com/v1/checkout/sessions", data=data,
                       headers={"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"}, timeout=20)
        if not r.is_success:
            return None, None, f"Stripe HTTP {r.status_code}: {r.text[:500]}"
        payload = r.json()
        return payload.get("url"), payload.get("id"), "Checkout Stripe creato"
    if provider == "external":
        template = settings.PAYMENT_EXTERNAL_URL_TEMPLATE or ""
        if not template:
            return None, None, "URL provider esterno non configurato"
        try:
            url = template.format(payment_id=payment.id, amount_cents=payment.amount_cents,
                                  amount=f"{payment.amount_cents/100:.2f}", currency=payment.currency,
                                  patient_id=payment.patient_id, booking_id=payment.booking_id or "")
        except Exception as exc:
            return None, None, f"Template provider esterno non valido: {exc}"
        return url, None, "Link provider esterno creato"
    return None, None, "Pagamento manuale: nessun dato carta gestito dal CUP"


def send_request(db, payment: PaymentRequest) -> list[dict]:
    patient = db.query(Patient).options(joinedload(Patient.user)).filter(Patient.id == payment.patient_id).first()
    if not patient:
        raise ValueError("Paziente non trovato")
    amount = f"{payment.amount_cents/100:.2f} {payment.currency}"
    text = settings.PAYMENT_REQUEST_TEMPLATE.format(description=payment.description, amount=amount, payment_url=public_url(payment.id))
    results = send_patient_message(patient, text, payment.channels, settings.PAYMENT_CHANNELS, subject="Richiesta di pagamento CUP")
    if any(x["ok"] for x in results):
        payment.status = "sent" if payment.status == "pending" else payment.status
        payment.sent_at = _utcnow()
    payment.provider_response = json.dumps(results, ensure_ascii=False)[:4000]
    db.commit(); db.refresh(payment)
    return results


def verify_stripe_signature(raw: bytes, signature_header: str) -> bool:
    secret = settings.STRIPE_WEBHOOK_SECRET or ""
    if not secret or not signature_header:
        return False
    parts = {}
    for part in signature_header.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            parts.setdefault(k.strip(), []).append(v.strip())
    try:
        ts = int(parts.get("t", ["0"])[0])
    except Exception:
        return False
    if abs(int(datetime.now(timezone.utc).timestamp()) - ts) > 300:
        return False
    signed = f"{ts}.".encode() + raw
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in parts.get("v1", []))
