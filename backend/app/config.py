from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_VERSION: str = "1.1.0"
    DEMO_DATA_ENABLED: bool = True
    DEMO_AUTO_SEED: bool = True
    DEMO_LOGIN_USERS_ENABLED: bool = True
    # Accesso semplificato per ambienti di sviluppo: scelta ruolo senza password.
    # Disabilitare obbligatoriamente in produzione.
    DEV_ROLE_LOGIN_ENABLED: bool = True

    DATABASE_URL: str = "postgresql://cup_admin:changeme@postgres:5432/cup_system"

    JWT_SECRET_KEY: str = "change_this_to_a_long_random_string"
    JWT_ALGORITHM: str = "HS256"
    OTP_DEMO_MODE: bool = True
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ADMIN_BOOTSTRAP_TOKEN: str = ""

    AMI_HOST: str = "asterisk"
    AMI_PORT: int = 5038
    AMI_USER: str = "cup_ami"
    AMI_PASSWORD: str = "changeme"
    AMI_LISTENER_ENABLED: bool = True

    LIVEKIT_URL: str = "ws://livekit:7880"
    LIVEKIT_API_KEY: str = "devkey"
    LIVEKIT_API_SECRET: str = "devsecret"

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    WHATSAPP_API_TOKEN: str = ""
    FACEBOOK_PAGE_TOKEN: str = ""

    # LLM OpenAI-compatible. Esempi: OpenAI, OpenRouter, LiteLLM locale.
    LLM_ENABLED: bool = False
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 700
    LLM_TIMEOUT_SECONDS: int = 45

    # Voice AI/NLU: l'LLM comprende intento e sentiment, ma non decide mai slot/prezzi/prenotazioni.
    VOICE_NLU_ENABLED: bool = True
    VOICE_AI_SERVICE_TOKEN: str = ""
    VOICE_NLU_CONFIDENCE_THRESHOLD: float = 0.62
    VOICE_MAX_UNDERSTANDING_FAILURES: int = 2
    VOICE_SENTIMENT_ENABLED: bool = True
    VOICE_SENTIMENT_HANDOFF_ENABLED: bool = True

    # Apprendimento supervisionato da operatori/chat e chiamate voce.
    TRAINING_ENABLED: bool = True
    TRAINING_CAPTURE_CHAT_ENABLED: bool = True
    TRAINING_CAPTURE_VOICE_ENABLED: bool = True
    TRAINING_REQUIRE_CONSENT: bool = True
    TRAINING_SERVICE_TOKEN: str = ""
    LIVEKIT_TRAINING_SYSTEM_PROMPT: str = "Usa gli esempi approvati CUP per metodo, tono e domande. Non inventare disponibilita, non memorizzare dati personali e passa a un umano quando necessario."

    # WhatsApp Business Cloud API.
    WHATSAPP_VERIFY_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_APP_SECRET: str = ""
    WHATSAPP_GRAPH_VERSION: str = "v23.0"

    # Handoff telefonico Asterisk.
    ASTERISK_HANDOFF_ENABLED: bool = False
    OPERATOR_EXTENSION: str = ""
    ASTERISK_CONTEXT: str = "from-internal"
    ASTERISK_CALLER_ID: str = "CUP AI <700>"
    AMI_ORIGINATE_CHANNEL: str = "Local/{extension}@from-internal"

    # Coda operatore / handoff AI -> umano.
    # manual: notifica e accettazione; auto_answer: assegna il primo disponibile; ring_group: notifica tutti, vince il primo che accetta.
    HANDOFF_MODE: str = "ring_group"
    HANDOFF_TIMEOUT_SECONDS: int = 30
    HANDOFF_TIMEOUT_ACTION: str = "callback"  # callback|return_ai|keep_waiting|voicemail
    HANDOFF_SERVICE_TOKEN: str = ""
    HANDOFF_BROWSER_NOTIFICATIONS: bool = True


    # Chatwoot operator queue / contact center.
    CHATWOOT_ENABLED: bool = False
    CHATWOOT_BASE_URL: str = ""
    CHATWOOT_ACCOUNT_ID: int = 0
    CHATWOOT_API_TOKEN: str = ""
    CHATWOOT_INBOX_IDENTIFIER: str = ""
    CHATWOOT_TEAM_ID: int = 0
    CHATWOOT_WEBHOOK_TOKEN: str = ""
    CHATWOOT_TIMEOUT_SECONDS: int = 20
    CHATWOOT_AUTO_SYNC_HANDOFF: bool = True
    # Hub conversazionale: Chatwoot e la console operatore; il CUP resta source-of-truth dei workflow.
    CHATWOOT_HUB_MODE: bool = True
    CUP_PUBLIC_BASE_URL: str = ""
    PATIENT_BOOKING_PATH: str = "/patient-portal.html?view=booking"

    # Test outbound chiamata paziente: il PBX deve avere il contesto indicato.
    ASTERISK_VOICE_TEST_ENABLED: bool = False
    ASTERISK_VOICE_TEST_CONTEXT: str = "cup-voice-ai-test"
    ASTERISK_VOICE_TEST_CHANNEL: str = "Local/{number}@from-internal"

    # Modalita prenotazioni dell'esercizio.
    # internal: modulo agende CUP; external: gestionale terzo nel frame; chatbot_only: nessun modulo prenotazioni.
    BOOKING_MODE: str = "internal"
    EXTERNAL_BOOKING_NAME: str = "Gestionale prenotazioni"
    EXTERNAL_BOOKING_URL: str = ""
    EXTERNAL_BOOKING_EMBED_ENABLED: bool = True

    # Calendar integration: Google Calendar OAuth refresh token.
    GOOGLE_CALENDAR_CLIENT_ID: str = ""
    GOOGLE_CALENDAR_CLIENT_SECRET: str = ""
    GOOGLE_CALENDAR_REFRESH_TOKEN: str = ""

    # Microsoft 365 / Graph application credentials.
    M365_TENANT_ID: str = ""
    M365_CLIENT_ID: str = ""
    M365_CLIENT_SECRET: str = ""

    # Promemoria appuntamenti.
    CLINIC_NAME: str = "Struttura Sanitaria"
    CLINIC_LOGO_PATH: str = ""
    REMINDERS_ENABLED: bool = True
    REMINDER_TEST_RECIPIENT: str = ""

    REMINDER_OFFSETS_HOURS: str = "48,24,2"
    REMINDER_CHANNELS: str = "sms,whatsapp,email"
    REMINDER_SEND_BOOKING_CONFIRMATION: bool = True
    REMINDER_ALLOW_CONFIRM_CANCEL: bool = True
    REMINDER_TOKEN_TTL_HOURS: int = 168
    REMINDER_POLL_SECONDS: int = 60
    REMINDER_MAX_ATTEMPTS: int = 3
    REMINDER_RETRY_MINUTES: int = 10
    REMINDER_TEMPLATE_CONFIRMATION: str = "CUP: appuntamento {service} il {date} alle {time}{doctor_text}. {action_text}"
    REMINDER_TEMPLATE_REMINDER: str = "Promemoria CUP: {service} il {date} alle {time}{doctor_text}. {action_text}"

    # Lista d attesa automatica
    WAITLIST_ENABLED: bool = True
    WAITLIST_OFFER_TTL_MINUTES: int = 20
    WAITLIST_MAX_CANDIDATES: int = 5

    # Pre-visita digitale e check-in.
    PREVISIT_ENABLED: bool = True
    PREVISIT_TOKEN_TTL_HOURS: int = 168
    PREVISIT_APPEND_TO_REMINDERS: bool = True

    # Continuità di cura: follow-up post visita e recall periodici
    FOLLOWUP_ENABLED: bool = True
    FOLLOWUP_DELAY_HOURS: int = 24
    FOLLOWUP_CHANNELS: str = "sms,whatsapp,email"
    FOLLOWUP_TOKEN_TTL_HOURS: int = 168
    FOLLOWUP_TEMPLATE: str = "CUP: come stai dopo {service}? Lascia un breve feedback o chiedi di essere ricontattato: {followup_url}"
    RECALL_ENABLED: bool = True
    RECALL_DEFAULT_DAYS: int = 365
    RECALL_CHANNELS: str = "sms,whatsapp,email"
    RECALL_TOKEN_TTL_HOURS: int = 720
    RECALL_TEMPLATE: str = "CUP: è il momento di programmare il controllo {service}. Prenota qui: {recall_url}"
    CARE_POLL_SECONDS: int = 60
    CHECKIN_ENABLED: bool = True
    CHECKIN_OPEN_HOURS_BEFORE: int = 6
    CHECKIN_CLOSE_HOURS_AFTER: int = 4


    # Pagamenti. Il CUP non acquisisce dati carta: Stripe usa Checkout ospitato.
    PAYMENTS_ENABLED: bool = True
    PAYMENT_PROVIDER: str = "manual"  # manual|stripe|external
    PAYMENT_DEFAULT_CURRENCY: str = "EUR"
    PAYMENT_CHANNELS: str = "sms,email,whatsapp"
    PAYMENT_LINK_TTL_HOURS: int = 168
    PAYMENT_REQUEST_TEMPLATE: str = "CUP: pagamento richiesto per {description}, importo {amount}. Apri il link sicuro: {payment_url}"
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    PAYMENT_SUCCESS_URL: str = ""
    PAYMENT_CANCEL_URL: str = ""
    PAYMENT_EXTERNAL_URL_TEMPLATE: str = ""

    # Firma documentale semplice con link sicuro, PDF immutabile e audit trail.
    SIGNATURES_ENABLED: bool = True
    SIGNATURE_CHANNELS: str = "sms,email,whatsapp"
    SIGNATURE_LINK_TTL_HOURS: int = 168
    SIGNATURE_UPLOAD_DIR: str = "/data/uploads/signatures"
    SIGNATURE_MAX_FILE_BYTES: int = 15 * 1024 * 1024
    SIGNATURE_REQUEST_TEMPLATE: str = "CUP: è richiesta la firma del documento {title}. Apri il link sicuro: {signature_url}"

    # SMTP opzionale per promemoria email.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True

    # SMS per continuazione sicura telefono -> web/chatbot.
    # Il gateway riceve JSON: {to, text, sender}. Se non configurato,
    # l'API genera comunque il link e ritorna modalita mock per collaudo.
    SMS_GATEWAY_URL: str = ""
    SMS_GATEWAY_TOKEN: str = ""
    SMS_SENDER: str = "CUP"
    SMS_TIMEOUT_SECONDS: int = 20
    CONTINUATION_TOKEN_TTL_MINUTES: int = 30

    # Upload documenti del chatbot pubblico.
    CHAT_UPLOAD_DIR: str = "/data/uploads/chat"
    CHAT_MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024
    CHAT_MAX_ATTACHMENTS: int = 10

    # Catalogo prestazioni mostrato dal chatbot pubblico.
    # Separare le voci con una virgola.
    CUP_SERVICES: str = (
        "Visita cardiologica,Visita dermatologica,Visita oculistica,"
        "Ecografia addome,Risonanza magnetica,Esami del sangue"
    )

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
