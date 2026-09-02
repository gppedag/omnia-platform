from __future__ import annotations
from app.services.whatsapp_utils import normalize_whatsapp_number

import asyncio
import json
import logging
import smtplib
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from html import escape as html_escape
from urllib.parse import quote

import httpx
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import joinedload

from app.config import settings
from app.db.database import SessionLocal
from app.models.booking import Booking
from app.models.patient import Patient
from app.models.reminder import AppointmentReminder

logger = logging.getLogger("reminder_service")


def _offsets() -> list[int]:
    out = []
    for raw in str(settings.REMINDER_OFFSETS_HOURS or "").split(","):
        try:
            value = int(raw.strip())
            if value >= 0 and value not in out:
                out.append(value)
        except Exception:
            continue
    return sorted(out, reverse=True)


def channel_configured(channel: str) -> bool:
    """
    Restituisce True soltanto se il provider del canale
    dispone della configurazione minima necessaria.

    In questo modo una preferenza paziente come
    "sms,whatsapp,email" non genera code destinate
    inevitabilmente a fallire.
    """
    channel = str(channel or "").strip().lower()

    if channel == "email":
        return bool(
            settings.SMTP_HOST
            and settings.SMTP_FROM
        )

    if channel == "sms":
        return bool(
            settings.SMS_GATEWAY_URL
        )

    if channel == "whatsapp":
        return bool(
            settings.WHATSAPP_API_TOKEN
            and settings.WHATSAPP_PHONE_NUMBER_ID
        )

    if channel == "telegram":
        return bool(
            settings.TELEGRAM_BOT_TOKEN
        )

    return False


def configured_reminder_channels() -> list[str]:
    return [
        channel
        for channel in (
            "sms",
            "whatsapp",
            "email",
            "telegram",
        )
        if channel_configured(channel)
    ]


def _channels(patient: Patient | None) -> list[str]:
    raw = (
        patient.reminder_channels
        if patient and patient.reminder_channels
        else settings.REMINDER_CHANNELS
    )

    allowed = {
        "sms",
        "whatsapp",
        "email",
        "telegram",
    }

    requested = [
        x.strip().lower()
        for x in str(raw or "").split(",")
        if x.strip().lower() in allowed
    ]

    # Manteniamo l'ordine scelto nelle preferenze,
    # ma escludiamo provider non configurati.
    return [
        channel
        for channel in requested
        if channel_configured(channel)
    ]




def provider_health(db, channel: str) -> dict:
    channel = str(channel or "").strip().lower()

    configured = channel_configured(channel)

    row = db.execute(
        text("""
            SELECT
                channel,
                status,
                consecutive_failures,
                last_error_code,
                last_error,
                last_success_at,
                suspended_at,
                updated_at
            FROM reminder_provider_health
            WHERE channel=:channel
        """),
        {"channel": channel},
    ).mappings().first()

    state = dict(row) if row else {
        "channel": channel,
        "status": "unknown",
        "consecutive_failures": 0,
        "last_error_code": None,
        "last_error": None,
        "last_success_at": None,
        "suspended_at": None,
        "updated_at": None,
    }

    state["configured"] = configured

    if not configured:
        state["status"] = "not_configured"

    return state


def channel_available(db, channel: str) -> bool:
    if not channel_configured(channel):
        return False

    state = provider_health(db, channel)

    return state.get("status") != "suspended"


def mark_provider_success(db, channel: str):
    db.execute(
        text("""
            INSERT INTO reminder_provider_health(
                channel,
                status,
                consecutive_failures,
                last_error_code,
                last_error,
                last_success_at,
                suspended_at,
                updated_at
            )
            VALUES(
                :channel,
                'operational',
                0,
                NULL,
                NULL,
                CURRENT_TIMESTAMP,
                NULL,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(channel)
            DO UPDATE SET
                status='operational',
                consecutive_failures=0,
                last_error_code=NULL,
                last_error=NULL,
                last_success_at=CURRENT_TIMESTAMP,
                suspended_at=NULL,
                updated_at=CURRENT_TIMESTAMP
        """),
        {"channel": channel},
    )


def mark_provider_failure(
    db,
    channel: str,
    detail: str,
):
    detail = str(detail or "")[:1000]

    permanent = False
    error_code = None

    if channel == "whatsapp":
        if (
            "HTTP 401" in detail
            or '"code":190' in detail
            or "Authentication Error" in detail
        ):
            permanent = True
            error_code = "META_AUTH_190"

    db.execute(
        text("""
            INSERT INTO reminder_provider_health(
                channel,
                status,
                consecutive_failures,
                last_error_code,
                last_error,
                suspended_at,
                updated_at
            )
            VALUES(
                :channel,
                :status,
                1,
                :error_code,
                :detail,
                CASE
                    WHEN :status='suspended'
                    THEN CURRENT_TIMESTAMP
                    ELSE NULL
                END,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(channel)
            DO UPDATE SET
                status=:status,
                consecutive_failures=
                    reminder_provider_health.consecutive_failures + 1,
                last_error_code=:error_code,
                last_error=:detail,
                suspended_at=
                    CASE
                        WHEN :status='suspended'
                        THEN COALESCE(
                            reminder_provider_health.suspended_at,
                            CURRENT_TIMESTAMP
                        )
                        ELSE reminder_provider_health.suspended_at
                    END,
                updated_at=CURRENT_TIMESTAMP
        """),
        {
            "channel": channel,
            "status": "suspended" if permanent else "degraded",
            "error_code": error_code,
            "detail": detail,
        },
    )

    return permanent


def reactivate_provider(db, channel: str):
    db.execute(
        text("""
            INSERT INTO reminder_provider_health(
                channel,
                status,
                consecutive_failures,
                updated_at
            )
            VALUES(
                :channel,
                'unknown',
                0,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(channel)
            DO UPDATE SET
                status='unknown',
                consecutive_failures=0,
                last_error_code=NULL,
                last_error=NULL,
                suspended_at=NULL,
                updated_at=CURRENT_TIMESTAMP
        """),
        {"channel": channel},
    )
    db.commit()

def patient_reminders_enabled(patient: Patient | None) -> bool:
    if not patient:
        return False
    return str(patient.reminder_enabled or "true").lower() not in {"false", "0", "no", "off"}


def _target(patient: Patient, channel: str) -> str | None:
    user = patient.user
    if channel in {"sms", "whatsapp"}:
        return (user.phone if user else None) or None
    if channel == "email":
        return (user.email if user else None) or None
    if channel == "telegram":
        return patient.reminder_telegram_chat_id or None
    return None


def create_action_token(booking_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(booking_id),
        "purpose": "booking_reminder_action",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.REMINDER_TOKEN_TTL_HOURS)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def resolve_action_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Link non valido o scaduto") from exc
    if payload.get("purpose") != "booking_reminder_action":
        raise ValueError("Link non valido")
    return int(payload["sub"])



def create_short_link(
    db,
    target_url: str,
    booking_id: int,
    purpose: str,
    ttl_hours: int | None = None,
) -> str:
    ttl = int(ttl_hours or settings.REMINDER_TOKEN_TTL_HOURS)
    expires_at = _utcnow() + timedelta(hours=ttl)

    for _ in range(10):
        code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]

        exists = db.execute(
            text("SELECT 1 FROM reminder_short_links WHERE code=:code"),
            {"code": code},
        ).first()

        if exists:
            continue

        db.execute(
            text("""
                INSERT INTO reminder_short_links(
                    code,
                    target_url,
                    booking_id,
                    purpose,
                    expires_at
                )
                VALUES(
                    :code,
                    :target_url,
                    :booking_id,
                    :purpose,
                    :expires_at
                )
            """),
            {
                "code": code,
                "target_url": target_url,
                "booking_id": booking_id,
                "purpose": purpose,
                "expires_at": expires_at,
            },
        )
        db.commit()

        base = settings.CUP_PUBLIC_BASE_URL.rstrip("/")
        return (
            f"{base}/api/reminders/short/{code}"
            if base
            else f"/api/reminders/short/{code}"
        )

    raise RuntimeError("Impossibile generare short link")


def reminder_links(db, booking: Booking) -> dict:
    action = action_url(booking.id)
    previsit = previsit_url(booking.id)

    return {
        "action": create_short_link(
            db,
            action,
            booking.id,
            "reminder_action",
        ),
        "previsit": create_short_link(
            db,
            previsit,
            booking.id,
            "previsit",
        ) if settings.PREVISIT_ENABLED and settings.PREVISIT_APPEND_TO_REMINDERS else None,
    }


def render_email_html(
    booking,
    action_link: str | None,
    previsit_link: str | None,
) -> str:
    """Email CUP essenziale: riepilogo, annullamento e pre-visita."""
    import html

    clinic = html.escape(
        str(getattr(settings, "CLINIC_NAME", "") or "Struttura Sanitaria")
    )
    service = html.escape(str(booking.service_name or "Appuntamento"))

    base_url = str(
        settings.CUP_PUBLIC_BASE_URL or ""
    ).rstrip("/")

    logo_url = None

    if getattr(settings, "CLINIC_LOGO_PATH", ""):
        logo_url = (
            f"{base_url}/api/settings/public/logo"
            if base_url
            else "/api/settings/public/logo"
        )

    logo_html = ""

    if logo_url:
        safe_logo = html.escape(
            logo_url,
            quote=True
        )

        logo_html = f"""
        <div style="margin-bottom:14px">
          <img
            src="{safe_logo}"
            alt="{clinic}"
            style="display:inline-block;
                   max-width:240px;
                   max-height:80px;
                   width:auto;
                   height:auto;
                   object-fit:contain">
        </div>
        """

    scheduled = booking.scheduled_at
    date_text = scheduled.strftime("%d/%m/%Y")
    time_text = scheduled.strftime("%H:%M")

    doctors = [
        html.escape(str(d.full_name))
        for d in (getattr(booking, "doctors", None) or [])
        if getattr(d, "full_name", None)
    ]
    doctor_text = ", ".join(doctors)

    agenda = getattr(booking, "agenda", None)
    location = html.escape(
        str(getattr(agenda, "location", "") or "")
    )

    cancel_button = ""
    if action_link:
        href = html.escape(str(action_link), quote=True)
        cancel_button = f"""
        <table role="presentation" cellspacing="0" cellpadding="0"
               border="0" align="center" style="margin:26px auto 12px">
          <tr>
            <td bgcolor="#dc3545" style="border-radius:7px">
              <a href="{href}"
                 style="display:inline-block;padding:13px 24px;
                        font-family:Arial,sans-serif;font-size:15px;
                        font-weight:bold;color:#ffffff;
                        text-decoration:none;border-radius:7px">
                Annulla appuntamento
              </a>
            </td>
          </tr>
        </table>
        """

    previsit_button = ""
    if previsit_link:
        href = html.escape(str(previsit_link), quote=True)
        previsit_button = f"""
        <table role="presentation" cellspacing="0" cellpadding="0"
               border="0" align="center" style="margin:12px auto">
          <tr>
            <td style="border:1px solid #0d6efd;border-radius:7px">
              <a href="{href}"
                 style="display:inline-block;padding:11px 22px;
                        font-family:Arial,sans-serif;font-size:14px;
                        font-weight:bold;color:#0d6efd;
                        text-decoration:none;border-radius:7px">
                Compila pre-visita
              </a>
            </td>
          </tr>
        </table>
        """

    doctor_row = (
        f'<div style="margin-top:7px;color:#344054">{doctor_text}</div>'
        if doctor_text else ""
    )
    location_row = (
        f'<div style="margin-top:7px;color:#667085">{location}</div>'
        if location else ""
    )

    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Promemoria appuntamento</title>
</head>
<body style="margin:0;padding:0;background:#f4f7fb">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"
       border="0" style="background:#f4f7fb">
<tr>
<td align="center" style="padding:28px 12px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"
       border="0"
       style="max-width:600px;background:#ffffff;border-radius:12px;
              overflow:hidden;border:1px solid #e4e7ec">
<tr>
<td style="padding:30px 32px;text-align:center;
           font-family:Arial,sans-serif">
  {logo_html}

  <div style="font-size:21px;font-weight:700;color:#101828">
    {clinic}
  </div>
  <div style="font-size:13px;color:#667085;margin-top:4px">
    Servizio Prenotazioni CUP
  </div>
</td>
</tr>

<tr>
<td style="padding:0 32px 30px;font-family:Arial,sans-serif">
  <div style="font-size:13px;text-transform:uppercase;
              letter-spacing:.06em;color:#667085;margin-bottom:8px">
    Promemoria appuntamento
  </div>

  <div style="font-size:23px;font-weight:700;color:#101828">
    {service}
  </div>

  <div style="font-size:17px;color:#344054;margin-top:16px">
    <strong>{date_text}</strong> &middot; {time_text}
  </div>

  {doctor_row}
  {location_row}

  <div style="height:1px;background:#eaecf0;margin:26px 0"></div>

  <div style="text-align:center;font-size:14px;color:#475467">
    Se non puoi presentarti, puoi annullare l'appuntamento.
  </div>

  {cancel_button}

  {previsit_button}

  <div style="text-align:center;font-size:12px;color:#98a2b3;
              margin-top:28px;line-height:1.5">
    Messaggio automatico del CUP<br>
    {clinic}
  </div>
</td>
</tr>
</table>
</td>
</tr>
</table>
</body>
</html>"""

def action_url(booking_id: int) -> str:
    token = create_action_token(booking_id)
    base = settings.CUP_PUBLIC_BASE_URL.rstrip("/")
    path = f"/reminder.html?token={quote(token, safe='')}"
    return base + path if base else path


def _booking_utc(booking: Booking) -> datetime:
    dt = booking.scheduled_at
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    tz_name = getattr(getattr(booking, "agenda", None), "timezone", None) or "Europe/Rome"
    try:
        return dt.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return dt


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _doctor_text(booking: Booking) -> str:
    names = [d.full_name for d in (booking.doctors or []) if getattr(d, "full_name", None)]
    return (" con " + ", ".join(names)) if names else ""


from app.services.previsit_service import previsit_url, checkin_url, ensure_previsit_for_booking

def render_message(booking: Booking, kind: str) -> str:
    dt = booking.scheduled_at
    action_text = ""
    if settings.REMINDER_ALLOW_CONFIRM_CANCEL:
        action_text = f"Conferma o annulla: {action_url(booking.id)}"
    template = settings.REMINDER_TEMPLATE_CONFIRMATION if kind == "confirmation" else settings.REMINDER_TEMPLATE_REMINDER
    values = dict(service=booking.service_name, date=dt.strftime("%d/%m/%Y"), time=dt.strftime("%H:%M"), doctor_text=_doctor_text(booking), action_text=action_text, booking_id=booking.id)
    try:
        text = template.format(**values).strip()
    except Exception:
        fallback = "Promemoria CUP: {service} il {date} alle {time}{doctor_text}. {action_text}"
        text = fallback.format(**values).strip()
    if settings.PREVISIT_ENABLED and settings.PREVISIT_APPEND_TO_REMINDERS:
        # Il link e' sicuro e idempotente; la pagina mostra "completato" se gia compilata.
        text += f" Pre-visita: {previsit_url(booking.id)}"
    if settings.CHECKIN_ENABLED and (booking.scheduled_at - datetime.now()).total_seconds() <= settings.CHECKIN_OPEN_HOURS_BEFORE * 3600:
        text += f" Check-in: {checkin_url(booking.id)}"
    return text


def ensure_booking_reminders(db, booking: Booking, include_confirmation: bool = False):
    if not settings.REMINDERS_ENABLED or booking.status in {"cancelled", "completed"}:
        return []
    patient = booking.patient
    if not patient_reminders_enabled(patient):
        return []
    channels = [
        channel
        for channel in _channels(patient)
        if channel_available(db, channel)
    ]
    now = _utcnow()
    created = []
    specs: list[tuple[str, int, datetime]] = []
    if include_confirmation and settings.REMINDER_SEND_BOOKING_CONFIRMATION:
        specs.append(("confirmation", -1, now))
    for offset in _offsets():
        due = _booking_utc(booking) - timedelta(hours=offset)
        # Non creare reminder ormai superati di oltre 10 minuti.
        if due >= now - timedelta(minutes=10):
            specs.append(("reminder", offset, due))
    for kind, offset, due in specs:
        for channel in channels:
            exists = db.query(AppointmentReminder).filter(
                AppointmentReminder.booking_id == booking.id,
                AppointmentReminder.kind == kind,
                AppointmentReminder.offset_hours == offset,
                AppointmentReminder.channel == channel,
                AppointmentReminder.scheduled_for == due,
                AppointmentReminder.status.in_(["pending", "sent", "skipped"]),
            ).first()
            if exists:
                continue
            target = _target(patient, channel)
            row = AppointmentReminder(
                booking_id=booking.id,
                kind=kind,
                offset_hours=offset,
                channel=channel,
                target=target,
                scheduled_for=due,
                status="pending" if target else "skipped",
                message=render_message(booking, kind),
                provider_response=None if target else "Nessun recapito disponibile",
            )
            db.add(row)
            created.append(row)
    db.commit()
    return created


def cancel_future_reminders(db, booking_id: int, reason: str = "Prenotazione annullata"):
    rows = db.query(AppointmentReminder).filter(
        AppointmentReminder.booking_id == booking_id,
        AppointmentReminder.status == "pending",
    ).all()
    for row in rows:
        row.status = "cancelled"
        row.provider_response = reason
    db.commit()


def rebuild_future_reminders(db, booking: Booking):
    # In caso di riprogrammazione, invalida i reminder non ancora spediti e crea una nuova pianificazione.
    rows = db.query(AppointmentReminder).filter(
        AppointmentReminder.booking_id == booking.id,
        AppointmentReminder.status == "pending",
    ).all()
    for row in rows:
        row.status = "cancelled"
        row.provider_response = "Riprogrammato"
    db.commit()
    return ensure_booking_reminders(db, booking, include_confirmation=False)


def _send_sms(target: str, text: str) -> tuple[bool, str]:
    if not settings.SMS_GATEWAY_URL:
        return False, "Gateway SMS non configurato"
    headers = {"Content-Type": "application/json"}
    if settings.SMS_GATEWAY_TOKEN:
        headers["Authorization"] = f"Bearer {settings.SMS_GATEWAY_TOKEN}"
    r = httpx.post(settings.SMS_GATEWAY_URL, headers=headers,
                   json={"to": target, "text": text, "sender": settings.SMS_SENDER},
                   timeout=settings.SMS_TIMEOUT_SECONDS)
    return r.is_success, f"HTTP {r.status_code}: {r.text[:300]}"


def _send_whatsapp(target: str, text: str) -> tuple[bool, str]:
    if not settings.WHATSAPP_API_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        return False, "WhatsApp non configurato"
    url = f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    r = httpx.post(url, headers={"Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}"},
                   json={
                       "messaging_product": "whatsapp",
                       "to": normalize_whatsapp_number(target),
                       "type": "text",
                       "text": {"body": text},
                   }, timeout=15)
    print(f"WHATSAPP_OUT target={normalize_whatsapp_number(target)} http={r.status_code} body={r.text[:500]}", flush=True)
    return r.is_success, f"HTTP {r.status_code}: {r.text[:300]}"


def _send_telegram(
    target: str,
    text: str,
    action_url: str | None = None,
    previsit_url: str | None = None,
) -> tuple[bool, str]:

    if not settings.TELEGRAM_BOT_TOKEN:
        return False, "Telegram non configurato"

    import httpx

    url = (
        f"https://api.telegram.org/"
        f"bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": target,
        "text": text,
        "disable_web_page_preview": True,
    }

    buttons = []

    if action_url:
        buttons.append([
            {
                "text": "Annulla appuntamento",
                "url": action_url,
            }
        ])

    if previsit_url:
        buttons.append([
            {
                "text": "Compila pre-visita",
                "url": previsit_url,
            }
        ])

    if buttons:
        payload["reply_markup"] = {
            "inline_keyboard": buttons
        }

    try:
        response = httpx.post(
            url,
            json=payload,
            timeout=20
        )

        ok = response.status_code == 200

        return (
            ok,
            f"HTTP {response.status_code}: "
            f"{response.text[:600]}"
        )

    except Exception as exc:
        return False, str(exc)
def _send_email(
    target: str,
    text: str,
    html: str | None = None,
) -> tuple[bool, str]:
    if not settings.SMTP_HOST or not settings.SMTP_FROM:
        return False, "SMTP non configurato"

    msg = EmailMessage()
    msg["Subject"] = f"Promemoria appuntamento - {getattr(settings, 'CLINIC_NAME', 'CUP')}"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = target

    msg.set_content(text)

    if html:
        msg.add_alternative(
            html,
            subtype="html",
        )

    with smtplib.SMTP(
        settings.SMTP_HOST,
        settings.SMTP_PORT,
        timeout=20
    ) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()

        if settings.SMTP_USER:
            smtp.login(
                settings.SMTP_USER,
                settings.SMTP_PASSWORD
            )

        smtp.send_message(msg)

    return True, "Email inviata"


def send_row(db, row: AppointmentReminder) -> AppointmentReminder:
    # Modalità test:
    # se configurata, nessun messaggio può essere inviato
    # a un destinatario diverso da quello autorizzato.
    test_recipient = str(
        getattr(settings, "REMINDER_TEST_RECIPIENT", "") or ""
    ).strip().lower()

    if test_recipient and row.channel == "email":
        target = str(row.target or "").strip().lower()

        if target != test_recipient:
            row.status = "skipped"
            row.provider_response = (
                "Bloccato dalla modalità test promemoria email"
            )
            db.commit()
            db.refresh(row)
            return row

    booking = db.query(Booking).options(
        joinedload(Booking.patient).joinedload(Patient.user),
        joinedload(Booking.doctors),
    ).filter(Booking.id == row.booking_id).first()
    if not booking or booking.status in {"cancelled", "completed"}:
        row.status = "skipped"
        row.provider_response = "Prenotazione non attiva"
        db.commit()
        return row
    row.message = render_message(booking, row.kind)
    row.attempts += 1
    try:
        fn = {"sms": _send_sms, "whatsapp": _send_whatsapp, "telegram": _send_telegram, "email": _send_email}.get(row.channel)
        if not fn or not row.target:
            ok, detail = False, "Canale o destinatario non disponibile"
        else:
            if row.channel == "email":
                links = reminder_links(db, booking)

                action_link = links.get("action")
                previsit_link = links.get("previsit")

                plain = (
                    f"{getattr(settings, 'CLINIC_NAME', 'Struttura Sanitaria')}\n"
                    f"Servizio Prenotazioni CUP\n\n"
                    f"Promemoria appuntamento\n\n"
                    f"{booking.service_name}\n"
                    f"{booking.scheduled_at.strftime('%d/%m/%Y')} · "
                    f"{booking.scheduled_at.strftime('%H:%M')}\n"
                    f"{_doctor_text(booking).strip()}\n\n"
                    f"Annulla appuntamento: {action_link or '-'}"
                )

                if previsit_link:
                    plain += f"\nPre-visita: {previsit_link}"

                html = render_email_html(
                    booking,
                    action_link,
                    previsit_link,
                )

                ok, detail = _send_email(
                    row.target,
                    plain,
                    html,
                )
            elif row.channel == "telegram":

                links = reminder_links(
                    db,
                    booking
                )

                clinic = (
                    getattr(
                        settings,
                        "CLINIC_NAME",
                        ""
                    )
                    or "Struttura Sanitaria"
                )

                doctor = (
                    _doctor_text(
                        booking
                    ).strip()
                )

                telegram_text = (
                    f"{clinic}\n\n"
                    f"Promemoria appuntamento CUP\n\n"
                    f"{booking.service_name}\n"
                    f"{booking.scheduled_at.strftime('%d/%m/%Y')} · "
                    f"{booking.scheduled_at.strftime('%H:%M')}"
                )

                if doctor:
                    telegram_text += (
                        f"\n{doctor}"
                    )

                ok, detail = _send_telegram(
                    row.target,
                    telegram_text,
                    links.get("action"),
                    links.get("previsit"),
                )

            else:
                ok, detail = fn(
                    row.target,
                    row.message
                )
        row.provider_response = detail

        if ok:
            mark_provider_success(
                db,
                row.channel,
            )

            row.status = "sent"
            row.sent_at = _utcnow()

        else:
            permanent = mark_provider_failure(
                db,
                row.channel,
                detail,
            )

            if permanent:
                row.status = "failed"
            else:
                row.status = (
                    "failed"
                    if row.attempts >= settings.REMINDER_MAX_ATTEMPTS
                    else "pending"
                )

                if row.status == "pending":
                    row.scheduled_for = (
                        _utcnow()
                        + timedelta(
                            minutes=settings.REMINDER_RETRY_MINUTES
                        )
                    )
    except Exception as exc:
        detail = str(exc)[:1000]

        row.provider_response = detail

        permanent = mark_provider_failure(
            db,
            row.channel,
            detail,
        )

        if permanent:
            row.status = "failed"
        else:
            row.status = (
                "failed"
                if row.attempts >= settings.REMINDER_MAX_ATTEMPTS
                else "pending"
            )

            if row.status == "pending":
                row.scheduled_for = (
                    _utcnow()
                    + timedelta(
                        minutes=settings.REMINDER_RETRY_MINUTES
                    )
                )
    db.commit()
    db.refresh(row)
    return row


def process_due_reminders() -> int:
    db = SessionLocal()
    sent = 0
    try:
        if not settings.REMINDERS_ENABLED:
            return 0
        # Assicura la pianificazione anche per prenotazioni create da vecchie API/import.
        horizon = datetime.now() + timedelta(hours=max(_offsets() or [0]) + 4)
        bookings = db.query(Booking).options(
            joinedload(Booking.patient).joinedload(Patient.user), joinedload(Booking.doctors)
        ).filter(Booking.status.in_(["pending", "confirmed"]), Booking.scheduled_at <= horizon, Booking.scheduled_at >= datetime.now()).all()
        for booking in bookings:
            ensure_booking_reminders(db, booking, include_confirmation=False)
        due = db.query(AppointmentReminder).filter(
            AppointmentReminder.status == "pending",
            AppointmentReminder.scheduled_for <= _utcnow(),
        ).order_by(AppointmentReminder.scheduled_for).limit(100).all()
        for row in due:
            before = row.status
            send_row(db, row)
            if before == "pending" and row.status == "sent":
                sent += 1
        return sent
    finally:
        db.close()


async def reminder_worker():
    while True:
        try:
            await asyncio.to_thread(process_due_reminders)
        except Exception:
            logger.exception("Errore worker promemoria")
        await asyncio.sleep(max(30, int(settings.REMINDER_POLL_SECONDS)))
