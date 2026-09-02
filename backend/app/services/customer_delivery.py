from __future__ import annotations
import smtplib
from email.message import EmailMessage

from app.config import settings
from app.models.patient import Patient
from app.services.reminder_service import _send_sms, _send_whatsapp, _send_telegram

ALLOWED = {"sms", "whatsapp", "telegram", "email"}


def patient_target(patient: Patient, channel: str) -> str | None:
    user = patient.user
    if channel in {"sms", "whatsapp"}:
        return (user.phone if user else None) or None
    if channel == "email":
        return (user.email if user else None) or None
    if channel == "telegram":
        return patient.reminder_telegram_chat_id or None
    return None


def normalize_channels(raw: str | None, fallback: str = "sms,email") -> list[str]:
    out = []
    for item in str(raw or fallback).split(","):
        item = item.strip().lower()
        if item in ALLOWED and item not in out:
            out.append(item)
    return out


def _send_email(target: str, text: str, subject: str) -> tuple[bool, str]:
    if not settings.SMTP_HOST or not settings.SMTP_FROM:
        return False, "SMTP non configurato"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = target
    msg.set_content(text)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)
    return True, "Email inviata"


def send_patient_message(patient: Patient, text: str, channels: str | None, fallback: str = "sms,email", subject: str = "Comunicazione CUP") -> list[dict]:
    results = []
    senders = {"sms": _send_sms, "whatsapp": _send_whatsapp, "telegram": _send_telegram}
    for channel in normalize_channels(channels, fallback):
        target = patient_target(patient, channel)
        if not target:
            results.append({"channel": channel, "ok": False, "detail": "Recapito non disponibile"})
            continue
        try:
            ok, detail = _send_email(target, text, subject) if channel == "email" else senders[channel](target, text)
        except Exception as exc:
            ok, detail = False, str(exc)
        results.append({"channel": channel, "ok": bool(ok), "detail": str(detail)[:500]})
    return results
