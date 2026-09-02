from __future__ import annotations
from typing import Any
from sqlalchemy.orm import Session
from app.config import settings
from app.models.system_setting import SystemSetting

# Campi modificabili da UI. DATABASE_URL/JWT restano fuori per non invalidare
# connessioni e sessioni mentre il processo e' in esecuzione.
SECTIONS = {
    "general": [
        "CLINIC_NAME", "CLINIC_LOGO_PATH", "CUP_PUBLIC_BASE_URL", "CUP_SERVICES", "CONTINUATION_TOKEN_TTL_MINUTES",
        "CHAT_MAX_UPLOAD_BYTES", "CHAT_MAX_ATTACHMENTS",
    ],
    "booking": [
        "BOOKING_MODE", "EXTERNAL_BOOKING_NAME", "EXTERNAL_BOOKING_URL", "EXTERNAL_BOOKING_EMBED_ENABLED",
    ],
    "asterisk": [
        "AMI_HOST", "AMI_PORT", "AMI_USER", "AMI_PASSWORD", "ASTERISK_HANDOFF_ENABLED",
        "OPERATOR_EXTENSION", "ASTERISK_CONTEXT", "ASTERISK_CALLER_ID", "AMI_ORIGINATE_CHANNEL",
        "HANDOFF_MODE", "HANDOFF_TIMEOUT_SECONDS", "HANDOFF_TIMEOUT_ACTION", "HANDOFF_SERVICE_TOKEN", "HANDOFF_BROWSER_NOTIFICATIONS",
    ],
    "telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET"],
    "whatsapp": [
        "WHATSAPP_API_TOKEN", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_APP_SECRET", "WHATSAPP_GRAPH_VERSION",
    ],
    "chatwoot": [
        "CHATWOOT_ENABLED", "CHATWOOT_BASE_URL", "CHATWOOT_ACCOUNT_ID", "CHATWOOT_API_TOKEN",
        "CHATWOOT_INBOX_IDENTIFIER", "CHATWOOT_TEAM_ID", "CHATWOOT_WEBHOOK_TOKEN",
        "CHATWOOT_TIMEOUT_SECONDS", "CHATWOOT_AUTO_SYNC_HANDOFF",
    ],
    "sms": ["SMS_GATEWAY_URL", "SMS_GATEWAY_TOKEN", "SMS_SENDER", "SMS_TIMEOUT_SECONDS"],
    "reminders": [
        "REMINDERS_ENABLED", "REMINDER_OFFSETS_HOURS", "REMINDER_CHANNELS", "REMINDER_SEND_BOOKING_CONFIRMATION",
        "REMINDER_ALLOW_CONFIRM_CANCEL", "REMINDER_TOKEN_TTL_HOURS", "REMINDER_POLL_SECONDS",
        "REMINDER_MAX_ATTEMPTS", "REMINDER_RETRY_MINUTES", "REMINDER_TEMPLATE_CONFIRMATION", "REMINDER_TEMPLATE_REMINDER",
        "WAITLIST_ENABLED", "WAITLIST_OFFER_TTL_MINUTES", "WAITLIST_MAX_CANDIDATES", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_USE_TLS",
    ],
    "previsit": ["PREVISIT_ENABLED", "PREVISIT_TOKEN_TTL_HOURS", "PREVISIT_APPEND_TO_REMINDERS", "CHECKIN_ENABLED", "CHECKIN_OPEN_HOURS_BEFORE", "CHECKIN_CLOSE_HOURS_AFTER"],
    "payments": ["PAYMENTS_ENABLED", "PAYMENT_PROVIDER", "PAYMENT_DEFAULT_CURRENCY", "PAYMENT_CHANNELS", "PAYMENT_LINK_TTL_HOURS", "PAYMENT_REQUEST_TEMPLATE", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "PAYMENT_SUCCESS_URL", "PAYMENT_CANCEL_URL", "PAYMENT_EXTERNAL_URL_TEMPLATE"],
    "signatures": ["SIGNATURES_ENABLED", "SIGNATURE_CHANNELS", "SIGNATURE_LINK_TTL_HOURS", "SIGNATURE_MAX_FILE_BYTES", "SIGNATURE_REQUEST_TEMPLATE"],
    "care": ["FOLLOWUP_ENABLED", "FOLLOWUP_DELAY_HOURS", "FOLLOWUP_CHANNELS", "FOLLOWUP_TOKEN_TTL_HOURS", "FOLLOWUP_TEMPLATE", "RECALL_ENABLED", "RECALL_DEFAULT_DAYS", "RECALL_CHANNELS", "RECALL_TOKEN_TTL_HOURS", "RECALL_TEMPLATE", "CARE_POLL_SECONDS"],
    "llm": [
        "LLM_ENABLED", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_TEMPERATURE",
        "LLM_MAX_TOKENS", "LLM_TIMEOUT_SECONDS",
        "TRAINING_ENABLED", "TRAINING_CAPTURE_CHAT_ENABLED", "TRAINING_CAPTURE_VOICE_ENABLED",
        "TRAINING_REQUIRE_CONSENT", "TRAINING_SERVICE_TOKEN", "LIVEKIT_TRAINING_SYSTEM_PROMPT",
    ],
    "livekit": ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"],
    "calendar_google": ["GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET", "GOOGLE_CALENDAR_REFRESH_TOKEN"],
    "calendar_microsoft365": ["M365_TENANT_ID", "M365_CLIENT_ID", "M365_CLIENT_SECRET"],
}

SECRET_FIELDS = {
    "AMI_PASSWORD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET", "WHATSAPP_API_TOKEN",
    "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "CHATWOOT_API_TOKEN", "CHATWOOT_WEBHOOK_TOKEN",
    "SMS_GATEWAY_TOKEN", "LLM_API_KEY", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET",
    "GOOGLE_CALENDAR_CLIENT_SECRET", "GOOGLE_CALENDAR_REFRESH_TOKEN", "M365_CLIENT_SECRET", "HANDOFF_SERVICE_TOKEN", "TRAINING_SERVICE_TOKEN", "SMTP_PASSWORD", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
}

FIELD_LABELS = {
    "CLINIC_NAME": "Nome struttura sanitaria",
    "CLINIC_LOGO_PATH": "Logo struttura sanitaria",
    "CUP_PUBLIC_BASE_URL": "URL pubblico CUP", "CUP_SERVICES": "Catalogo prestazioni",
    "BOOKING_MODE": "Modalità prenotazioni", "EXTERNAL_BOOKING_NAME": "Nome gestionale esterno",
    "EXTERNAL_BOOKING_URL": "URL gestionale esterno", "EXTERNAL_BOOKING_EMBED_ENABLED": "Mostra il gestionale nel frame CUP",
    "CONTINUATION_TOKEN_TTL_MINUTES": "Durata link SMS (minuti)",
    "CHAT_MAX_UPLOAD_BYTES": "Dimensione massima upload (byte)", "CHAT_MAX_ATTACHMENTS": "Numero massimo allegati",
    "AMI_HOST": "Host AMI", "AMI_PORT": "Porta AMI", "AMI_USER": "Utente AMI", "AMI_PASSWORD": "Password AMI",
    "ASTERISK_HANDOFF_ENABLED": "Handoff telefonico abilitato", "OPERATOR_EXTENSION": "Interno operatore",
    "ASTERISK_CONTEXT": "Context Asterisk", "ASTERISK_CALLER_ID": "Caller ID", "AMI_ORIGINATE_CHANNEL": "Canale Originate",
    "HANDOFF_MODE": "Modalità handoff", "HANDOFF_TIMEOUT_SECONDS": "Timeout accettazione (secondi)",
    "HANDOFF_TIMEOUT_ACTION": "Azione al timeout", "HANDOFF_SERVICE_TOKEN": "Token servizio LiveKit/voice",
    "HANDOFF_BROWSER_NOTIFICATIONS": "Notifiche browser",
    "TELEGRAM_BOT_TOKEN": "Bot token", "TELEGRAM_WEBHOOK_SECRET": "Webhook secret",
    "WHATSAPP_API_TOKEN": "API token", "WHATSAPP_VERIFY_TOKEN": "Verify token", "WHATSAPP_PHONE_NUMBER_ID": "Phone Number ID",
    "WHATSAPP_APP_SECRET": "App secret", "WHATSAPP_GRAPH_VERSION": "Graph API version",
    "CHATWOOT_ENABLED": "Chatwoot abilitato", "CHATWOOT_BASE_URL": "Base URL", "CHATWOOT_ACCOUNT_ID": "Account ID",
    "CHATWOOT_API_TOKEN": "API token", "CHATWOOT_INBOX_IDENTIFIER": "Inbox identifier", "CHATWOOT_TEAM_ID": "Team ID",
    "CHATWOOT_WEBHOOK_TOKEN": "Webhook token", "CHATWOOT_TIMEOUT_SECONDS": "Timeout (secondi)",
    "CHATWOOT_AUTO_SYNC_HANDOFF": "Sync automatico su handoff",
    "SMS_GATEWAY_URL": "Gateway URL", "SMS_GATEWAY_TOKEN": "Gateway token", "SMS_SENDER": "Mittente SMS", "SMS_TIMEOUT_SECONDS": "Timeout (secondi)",
    "LLM_ENABLED": "LLM abilitato", "LLM_BASE_URL": "Base URL OpenAI-compatible", "LLM_API_KEY": "API key", "LLM_MODEL": "Modello",
    "LLM_TEMPERATURE": "Temperature", "LLM_MAX_TOKENS": "Max token", "LLM_TIMEOUT_SECONDS": "Timeout (secondi)",
    "TRAINING_ENABLED": "Apprendimento supervisionato abilitato", "TRAINING_CAPTURE_CHAT_ENABLED": "Raccogli esempi dalle chat operatore",
    "TRAINING_CAPTURE_VOICE_ENABLED": "Raccogli esempi dalle chiamate con consenso", "TRAINING_REQUIRE_CONSENT": "Consenso obbligatorio per training voce",
    "TRAINING_SERVICE_TOKEN": "Token servizio trascrizioni LiveKit", "LIVEKIT_TRAINING_SYSTEM_PROMPT": "Istruzioni metodo per voice agent LiveKit",
    "LIVEKIT_URL": "LiveKit URL", "LIVEKIT_API_KEY": "API key", "LIVEKIT_API_SECRET": "API secret",
    "GOOGLE_CALENDAR_CLIENT_ID": "Google OAuth Client ID", "GOOGLE_CALENDAR_CLIENT_SECRET": "Google OAuth Client Secret",
    "GOOGLE_CALENDAR_REFRESH_TOKEN": "Google Refresh Token", "M365_TENANT_ID": "Microsoft Tenant ID",
    "M365_CLIENT_ID": "Microsoft Client ID", "M365_CLIENT_SECRET": "Microsoft Client Secret",
    "PREVISIT_ENABLED": "Pre-visita digitale abilitata", "PREVISIT_TOKEN_TTL_HOURS": "Validità link pre-visita (ore)",
    "PREVISIT_APPEND_TO_REMINDERS": "Aggiungi link pre-visita ai promemoria", "CHECKIN_ENABLED": "Check-in digitale abilitato",
    "CHECKIN_OPEN_HOURS_BEFORE": "Apertura check-in (ore prima)", "CHECKIN_CLOSE_HOURS_AFTER": "Chiusura check-in (ore dopo)",
    "REMINDERS_ENABLED": "Promemoria abilitati", "REMINDER_OFFSETS_HOURS": "Invii prima dell'appuntamento (ore, separati da virgola)",
    "REMINDER_CHANNELS": "Canali predefiniti (sms,whatsapp,email,telegram)", "REMINDER_SEND_BOOKING_CONFIRMATION": "Invia conferma alla creazione",
    "REMINDER_ALLOW_CONFIRM_CANCEL": "Consenti conferma/annullamento da link", "REMINDER_TOKEN_TTL_HOURS": "Validità link azione (ore)",
    "REMINDER_POLL_SECONDS": "Frequenza controllo coda (secondi)", "REMINDER_MAX_ATTEMPTS": "Tentativi massimi per invio",
    "REMINDER_RETRY_MINUTES": "Ritenta dopo (minuti)", "REMINDER_TEMPLATE_CONFIRMATION": "Template conferma prenotazione",
    "REMINDER_TEMPLATE_REMINDER": "Template promemoria", "WAITLIST_ENABLED": "Lista d attesa automatica abilitata", "WAITLIST_OFFER_TTL_MINUTES": "Validità proposta lista d attesa (minuti)", "WAITLIST_MAX_CANDIDATES": "Pazienti contattati per ogni slot", "SMTP_HOST": "SMTP host", "SMTP_PORT": "SMTP porta",
    "SMTP_USER": "SMTP utente", "SMTP_PASSWORD": "SMTP password", "SMTP_FROM": "Mittente email", "SMTP_USE_TLS": "SMTP STARTTLS",
    "FOLLOWUP_ENABLED": "Follow-up post-visita abilitato", "FOLLOWUP_DELAY_HOURS": "Invia follow-up dopo (ore)",
    "FOLLOWUP_CHANNELS": "Canali follow-up", "FOLLOWUP_TOKEN_TTL_HOURS": "Validità link follow-up (ore)",
    "FOLLOWUP_TEMPLATE": "Template follow-up", "RECALL_ENABLED": "Recall periodici abilitati",
    "RECALL_DEFAULT_DAYS": "Richiamo predefinito dopo (giorni)", "RECALL_CHANNELS": "Canali recall",
    "RECALL_TOKEN_TTL_HOURS": "Validità link recall (ore)", "RECALL_TEMPLATE": "Template recall",
    "CARE_POLL_SECONDS": "Frequenza controllo automazioni (secondi)",
    "PAYMENTS_ENABLED": "Pagamenti abilitati", "PAYMENT_PROVIDER": "Provider pagamenti",
    "PAYMENT_DEFAULT_CURRENCY": "Valuta predefinita", "PAYMENT_CHANNELS": "Canali richiesta pagamento",
    "PAYMENT_LINK_TTL_HOURS": "Validità link pagamento (ore)", "PAYMENT_REQUEST_TEMPLATE": "Template richiesta pagamento",
    "STRIPE_SECRET_KEY": "Stripe secret key", "STRIPE_WEBHOOK_SECRET": "Stripe webhook secret",
    "PAYMENT_SUCCESS_URL": "URL ritorno pagamento riuscito", "PAYMENT_CANCEL_URL": "URL ritorno pagamento annullato",
    "PAYMENT_EXTERNAL_URL_TEMPLATE": "Template URL provider esterno",
    "SIGNATURES_ENABLED": "Firma documentale abilitata", "SIGNATURE_CHANNELS": "Canali richiesta firma",
    "SIGNATURE_LINK_TTL_HOURS": "Validità link firma (ore)", "SIGNATURE_MAX_FILE_BYTES": "Dimensione massima PDF (byte)",
    "SIGNATURE_REQUEST_TEMPLATE": "Template richiesta firma",
}


def _cast(key: str, value: Any):
    current = getattr(settings, key)
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on", "si", "sì"}
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return str(value or "")


def apply_value(key: str, value: Any):
    setattr(settings, key, _cast(key, value))


def load_overrides(db: Session):
    allowed = {k for fields in SECTIONS.values() for k in fields}
    for row in db.query(SystemSetting).all():
        if row.key in allowed:
            try:
                apply_value(row.key, row.value)
            except Exception:
                pass


def save_overrides(db: Session, values: dict[str, Any]):
    allowed = {k for fields in SECTIONS.values() for k in fields}
    changed = []
    for key, raw in values.items():
        if key not in allowed:
            continue
        # Segreti vuoti significano "mantieni il valore esistente".
        if key in SECRET_FIELDS and (raw is None or str(raw).strip() == ""):
            continue
        casted = _cast(key, raw)
        if key == "HANDOFF_MODE" and casted not in {"manual", "auto_answer", "ring_group"}:
            raise ValueError("HANDOFF_MODE deve essere manual, auto_answer o ring_group")
        if key == "HANDOFF_TIMEOUT_ACTION" and casted not in {"callback", "return_ai", "keep_waiting", "voicemail"}:
            raise ValueError("HANDOFF_TIMEOUT_ACTION non valido")
        if key == "PAYMENT_PROVIDER" and casted not in {"manual", "stripe", "external"}:
            raise ValueError("PAYMENT_PROVIDER deve essere manual, stripe o external")
        if key == "BOOKING_MODE" and casted not in {"internal", "external", "chatbot_only"}:
            raise ValueError("BOOKING_MODE deve essere internal, external o chatbot_only")
        if key == "EXTERNAL_BOOKING_URL" and casted and not str(casted).lower().startswith(("https://", "http://")):
            raise ValueError("EXTERNAL_BOOKING_URL deve iniziare con http:// o https://")
        stored = "true" if casted is True else "false" if casted is False else str(casted)
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row:
            row.value = stored
        else:
            db.add(SystemSetting(key=key, value=stored))
        setattr(settings, key, casted)
        changed.append(key)
    db.commit()
    return changed


def public_schema():
    result = []
    for section, fields in SECTIONS.items():
        items = []
        for key in fields:
            value = getattr(settings, key)
            secret = key in SECRET_FIELDS
            items.append({
                "key": key,
                "label": FIELD_LABELS.get(key, key),
                "value": "" if secret else value,
                "secret": secret,
                "configured": bool(value) if secret else None,
                "type": "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "number" if isinstance(value, float) else "string",
            })
        result.append({"section": section, "fields": items})
    return result
