from __future__ import annotations
import asyncio
from urllib.parse import urlparse
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_role
from app.config import settings
from app.db.database import get_db
from app.services.runtime_settings import public_schema, save_overrides

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    values: dict


class ChannelMessageTest(BaseModel):
    destination: str = Field(min_length=1, max_length=100)
    message: str = Field(default="Ciao, questo è un messaggio di test del CUP AI.", max_length=1000)


@router.get("")
def get_settings(db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    return {"version": settings.APP_VERSION, "sections": public_schema()}




@router.get("/runtime")
def runtime_settings(user=Depends(require_role("admin", "operator"))):
    return {
        "booking_mode": settings.BOOKING_MODE,
        "external_booking_name": settings.EXTERNAL_BOOKING_NAME,
        "external_booking_url": settings.EXTERNAL_BOOKING_URL,
        "external_booking_embed_enabled": settings.EXTERNAL_BOOKING_EMBED_ENABLED,
        "payments_enabled": settings.PAYMENTS_ENABLED,
        "payment_provider": settings.PAYMENT_PROVIDER,
        "signatures_enabled": settings.SIGNATURES_ENABLED,
    }


@router.put("")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    try:
        changed = save_overrides(db, payload.values)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"Valore non valido: {exc}")
    return {"ok": True, "changed": changed, "restart_recommended": any(k.startswith("AMI_") for k in changed)}


async def _tcp_test(host: str, port: int):
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=4)
        writer.close()
        await writer.wait_closed()
        return {"ok": True, "message": f"Connessione TCP riuscita a {host}:{port}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@router.post("/test/{section}")
async def test_setting(section: str, user=Depends(require_role("admin"))):
    try:
        if section == "asterisk":
            return await _tcp_test(settings.AMI_HOST, settings.AMI_PORT)
        if section == "telegram":
            if not settings.TELEGRAM_BOT_TOKEN:
                return {"ok": False, "message": "Bot token non configurato"}
            r = httpx.get(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getMe", timeout=8)
            body = r.json()
            return {"ok": bool(r.is_success and body.get("ok")), "message": body.get("description") or (body.get("result") or {}).get("username") or f"HTTP {r.status_code}"}
        if section == "whatsapp":
            if not settings.WHATSAPP_API_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
                return {"ok": False, "message": "API token o Phone Number ID non configurato"}
            r = httpx.get(
                f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}",
                headers={"Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}"}, timeout=8,
            )
            return {"ok": r.is_success, "message": f"WhatsApp Graph API HTTP {r.status_code}"}
        if section == "chatwoot":
            if not settings.CHATWOOT_BASE_URL or not settings.CHATWOOT_API_TOKEN:
                return {"ok": False, "message": "URL o API token non configurati"}
            r = httpx.get(settings.CHATWOOT_BASE_URL.rstrip("/") + "/api/v1/profile", headers={"api_access_token": settings.CHATWOOT_API_TOKEN}, timeout=8)
            return {"ok": r.is_success, "message": f"Chatwoot HTTP {r.status_code}"}
        if section == "llm":
            if not settings.LLM_BASE_URL:
                return {"ok": False, "message": "Base URL LLM non configurata"}
            headers = {"Authorization": f"Bearer {settings.LLM_API_KEY}"} if settings.LLM_API_KEY else {}
            r = httpx.get(settings.LLM_BASE_URL.rstrip("/") + "/models", headers=headers, timeout=8)
            return {"ok": r.is_success, "message": f"LLM /models HTTP {r.status_code}"}
        if section == "livekit":
            p = urlparse(settings.LIVEKIT_URL)
            host = p.hostname or "livekit"
            port = p.port or (443 if p.scheme in {"wss", "https"} else 7880)
            return await _tcp_test(host, port)
        if section == "sms":
            return {"ok": bool(settings.SMS_GATEWAY_URL), "message": "Gateway SMS configurato" if settings.SMS_GATEWAY_URL else "Gateway SMS non configurato: modalita mock attiva"}
        if section == "reminders":
            channels = [x.strip() for x in settings.REMINDER_CHANNELS.split(",") if x.strip()]
            checks = {
                "sms": bool(settings.SMS_GATEWAY_URL),
                "whatsapp": bool(settings.WHATSAPP_API_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID),
                "telegram": bool(settings.TELEGRAM_BOT_TOKEN),
                "email": bool(settings.SMTP_HOST and settings.SMTP_FROM),
            }
            configured = [c for c in channels if checks.get(c)]
            missing = [c for c in channels if not checks.get(c)]
            return {"ok": bool(settings.REMINDERS_ENABLED and configured), "message": f"Attivi: {', '.join(configured) or 'nessuno'}" + (f" · Da configurare: {', '.join(missing)}" if missing else "")}
        if section == "previsit":
            return {"ok": bool(settings.PREVISIT_ENABLED or settings.CHECKIN_ENABLED), "message": f"Pre-visita: {'ON' if settings.PREVISIT_ENABLED else 'OFF'} · Check-in: {'ON' if settings.CHECKIN_ENABLED else 'OFF'}"}
        if section == "care":
            return {"ok": bool(settings.FOLLOWUP_ENABLED or settings.RECALL_ENABLED), "message": f"Follow-up: {'ON' if settings.FOLLOWUP_ENABLED else 'OFF'} · Recall: {'ON' if settings.RECALL_ENABLED else 'OFF'}"}
        if section == "payments":
            provider = (settings.PAYMENT_PROVIDER or "manual").lower()
            if provider == "stripe":
                return {"ok": bool(settings.PAYMENTS_ENABLED and settings.STRIPE_SECRET_KEY), "message": "Stripe Checkout configurato" if settings.STRIPE_SECRET_KEY else "Stripe selezionato: secret key mancante"}
            if provider == "external":
                return {"ok": bool(settings.PAYMENTS_ENABLED and settings.PAYMENT_EXTERNAL_URL_TEMPLATE), "message": "Provider esterno configurato" if settings.PAYMENT_EXTERNAL_URL_TEMPLATE else "Template URL provider esterno mancante"}
            return {"ok": bool(settings.PAYMENTS_ENABLED), "message": "Modalità pagamento manuale: il CUP non acquisisce dati carta"}
        if section == "signatures":
            return {"ok": bool(settings.SIGNATURES_ENABLED), "message": "Firma documentale semplice attiva" if settings.SIGNATURES_ENABLED else "Firma documentale disabilitata"}
        if section == "booking":
            mode = settings.BOOKING_MODE
            if mode == "external" and not settings.EXTERNAL_BOOKING_URL:
                return {"ok": False, "message": "Modalità esterna selezionata ma URL gestionale non configurato"}
            labels = {"internal": "Modulo Agende CUP interno", "external": f"Gestionale esterno: {settings.EXTERNAL_BOOKING_NAME}", "chatbot_only": "Solo chatbot: prenotazioni disabilitate"}
            return {"ok": True, "message": labels.get(mode, mode)}
        if section == "calendar_google":
            from app.services.external_calendar import test_provider
            return await test_provider("google")
        if section == "calendar_microsoft365":
            from app.services.external_calendar import test_provider
            return await test_provider("microsoft365")
        if section == "general":
            return {"ok": True, "message": f"URL pubblico: {settings.CUP_PUBLIC_BASE_URL or 'non configurato'}"}
        raise HTTPException(status_code=404, detail="Sezione non riconosciuta")
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@router.post("/test-message/{channel}")
async def test_message(channel: str, payload: ChannelMessageTest, user=Depends(require_role("admin"))):
    if channel == "telegram":
        if not settings.TELEGRAM_BOT_TOKEN:
            return {"ok": False, "message": "TELEGRAM_BOT_TOKEN non configurato"}
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            r = httpx.post(url, json={"chat_id": payload.destination.strip(), "text": payload.message}, timeout=15)
            body = r.json() if r.content else {}
            ok = bool(r.is_success and body.get("ok"))
            return {"ok": ok, "message": "Messaggio Telegram inviato" if ok else body.get("description", f"Telegram HTTP {r.status_code}")}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
    if channel == "phone":
        from app.services.asterisk_gateway import originate_patient_test_call
        result = await originate_patient_test_call(payload.destination, payload.message)
        return {"ok": bool(result.get("ok")), "message": "Chiamata test avviata" if result.get("ok") else result.get("reason", "Originate fallito"), "detail": result}
    raise HTTPException(status_code=404, detail="Canale di test non riconosciuto")


# CUP_CLINIC_BRANDING_V1

from pathlib import Path as FsPath
import shutil
import mimetypes

from fastapi import UploadFile, File
from fastapi.responses import FileResponse

from app.models.system_setting import SystemSetting


BRANDING_DIR = FsPath("/app/data/branding")

ALLOWED_LOGO_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}

MAX_LOGO_BYTES = 2 * 1024 * 1024


def _branding_public_logo_url():
    if not settings.CLINIC_LOGO_PATH:
        return None

    base = str(settings.CUP_PUBLIC_BASE_URL or "").rstrip("/")

    if base:
        return f"{base}/api/settings/public/logo"

    return "/api/settings/public/logo"


@router.get("/public/branding")
def public_branding():
    return {
        "clinic_name": (
            settings.CLINIC_NAME
            or "Struttura Sanitaria"
        ),
        "logo_url": _branding_public_logo_url(),
    }


@router.get("/public/logo")
def public_clinic_logo():
    raw = str(settings.CLINIC_LOGO_PATH or "").strip()

    if not raw:
        raise HTTPException(
            status_code=404,
            detail="Logo non configurato",
        )

    path = FsPath(raw)

    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Logo non disponibile",
        )

    media_type, _ = mimetypes.guess_type(str(path))

    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=3600"
        },
    )


@router.post("/branding/logo")
async def upload_clinic_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    content_type = (
        file.content_type or ""
    ).lower()

    extension = ALLOWED_LOGO_TYPES.get(content_type)

    if not extension:
        raise HTTPException(
            status_code=400,
            detail=(
                "Formato logo non valido. "
                "Usa PNG, JPG, WEBP o SVG."
            ),
        )

    data = await file.read(
        MAX_LOGO_BYTES + 1
    )

    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(
            status_code=400,
            detail="Il logo non può superare 2 MB",
        )

    if not data:
        raise HTTPException(
            status_code=400,
            detail="File logo vuoto",
        )

    BRANDING_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Rimuove il logo precedente.
    for old in BRANDING_DIR.glob("clinic-logo.*"):
        try:
            old.unlink()
        except Exception:
            pass

    destination = (
        BRANDING_DIR
        / f"clinic-logo{extension}"
    )

    destination.write_bytes(data)

    value = str(destination)

    row = (
        db.query(SystemSetting)
        .filter(
            SystemSetting.key
            == "CLINIC_LOGO_PATH"
        )
        .first()
    )

    if row:
        row.value = value
    else:
        db.add(
            SystemSetting(
                key="CLINIC_LOGO_PATH",
                value=value,
            )
        )

    settings.CLINIC_LOGO_PATH = value

    db.commit()

    return {
        "ok": True,
        "logo_url": _branding_public_logo_url(),
    }


@router.delete("/branding/logo")
def delete_clinic_logo(
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    raw = str(
        settings.CLINIC_LOGO_PATH or ""
    ).strip()

    if raw:
        try:
            FsPath(raw).unlink(
                missing_ok=True
            )
        except Exception:
            pass

    row = (
        db.query(SystemSetting)
        .filter(
            SystemSetting.key
            == "CLINIC_LOGO_PATH"
        )
        .first()
    )

    if row:
        row.value = ""

    settings.CLINIC_LOGO_PATH = ""

    db.commit()

    return {"ok": True}

# /CUP_CLINIC_BRANDING_V1
