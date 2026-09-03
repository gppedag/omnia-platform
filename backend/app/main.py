import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.database import Base, engine
from app.api import auth_routes, patient_routes, patient_relationship_routes, booking_routes, call_routes, chatbot_routes, omnichannel_routes, chatwoot_routes, settings_routes, calendar_routes, handoff_routes, reminder_routes, demo_routes, waitlist_routes, previsit_routes, care_routes, analytics_routes, operator_routes, payment_routes, signature_routes, training_routes, portal_routes, voice_routes
from app.api import patient_identity_routes
from app.api import voice_upgrade_routes
from app.api import admin_catalog_routes
from app.api import booking_eligibility_routes
from app.api import admin_agenda_visit_routes
from app.api import admin_settings_routes
from app.api import reallocation_routes

try:
    from app.api import livekit_routes
except ImportError as exc:
    livekit_routes = None
    _livekit_import_error = exc
from app.services.ami_listener import start_ami_listener

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cup_system")

app = FastAPI(title="CUP System API", version=settings.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(patient_routes.router)
app.include_router(patient_relationship_routes.router)
app.include_router(booking_routes.router)
app.include_router(call_routes.router)
if livekit_routes is not None:
    app.include_router(livekit_routes.router)
else:
    logger.warning("LiveKit API disabilitata: dipendenza opzionale non installata (%s)", _livekit_import_error)
app.include_router(chatbot_routes.router)
app.include_router(omnichannel_routes.router)
app.include_router(chatwoot_routes.router)
app.include_router(settings_routes.router)
app.include_router(calendar_routes.router)
app.include_router(reallocation_routes.router)
app.include_router(handoff_routes.router)
app.include_router(reminder_routes.router)
app.include_router(demo_routes.router)
app.include_router(waitlist_routes.router)
app.include_router(previsit_routes.router)
app.include_router(care_routes.router)
app.include_router(analytics_routes.router)
app.include_router(operator_routes.router)
app.include_router(payment_routes.router)
app.include_router(signature_routes.router)
app.include_router(training_routes.router)
app.include_router(portal_routes.router)
app.include_router(voice_routes.router)
app.include_router(patient_identity_routes.router)
app.include_router(voice_upgrade_routes.router)
app.include_router(admin_catalog_routes.router)
app.include_router(booking_eligibility_routes.router)
app.include_router(admin_agenda_visit_routes.router)
app.include_router(admin_settings_routes.router)




from fastapi.responses import RedirectResponse
from sqlalchemy import text as sql_text
from app.db.database import SessionLocal


@app.get("/r/{code}", include_in_schema=False)
def resolve_public_short_link(code: str):
    db = SessionLocal()

    try:
        row = db.execute(
            sql_text("""
                SELECT target_url, expires_at
                FROM reminder_short_links
                WHERE code=:code
            """),
            {"code": code},
        ).mappings().first()

        if not row:
            from fastapi import HTTPException
            raise HTTPException(404, "Link non trovato")

        from datetime import datetime

        if (
            row["expires_at"]
            and row["expires_at"] < datetime.utcnow()
        ):
            from fastapi import HTTPException
            raise HTTPException(410, "Link scaduto")

        return RedirectResponse(
            row["target_url"],
            status_code=302
        )

    finally:
        db.close()


@app.on_event("startup")
async def on_startup():
    from app.models import waitlist as _waitlist_models
    from app.models import previsit as _previsit_models
    from app.models import care as _care_models
    from app.models import training as _training_models
    from app.models import portal as _portal_models
    Base.metadata.create_all(bind=engine)
    # Migrazione retrocompatibile per prenotazioni create dalle release <=1.0.12.
    # create_all crea le nuove tabelle ma non aggiunge colonne a tabelle esistenti.
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS end_at TIMESTAMP"))
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS agenda_id INTEGER"))
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS visit_type_id INTEGER"))
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS external_provider VARCHAR(30)"))
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS external_event_id VARCHAR(512)"))
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS external_sync_status VARCHAR(255)"))
        conn.execute(text("UPDATE bookings SET end_at = scheduled_at + interval '30 minutes' WHERE end_at IS NULL"))
        conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS reminder_enabled VARCHAR(10) DEFAULT 'true'"))
        conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS reminder_channels VARCHAR(120)"))
        conn.execute(text("ALTER TABLE patients ADD COLUMN IF NOT EXISTS reminder_telegram_chat_id VARCHAR(120)"))
        conn.execute(text("ALTER TABLE visit_types ADD COLUMN IF NOT EXISTS recall_enabled BOOLEAN DEFAULT true"))
        conn.execute(text("ALTER TABLE visit_types ADD COLUMN IF NOT EXISTS recall_days INTEGER"))
        conn.execute(text("ALTER TABLE visit_types ADD COLUMN IF NOT EXISTS followup_enabled BOOLEAN DEFAULT true"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS can_chat BOOLEAN DEFAULT true"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS can_phone BOOLEAN DEFAULT true"))
        conn.execute(text("UPDATE users SET can_chat=true WHERE can_chat IS NULL"))
        conn.execute(text("UPDATE users SET can_phone=true WHERE can_phone IS NULL"))
        conn.execute(text("ALTER TABLE visit_types ADD COLUMN IF NOT EXISTS private_price_cents INTEGER DEFAULT 0"))
        conn.execute(text("ALTER TABLE visit_types ADD COLUMN IF NOT EXISTS ssn_enabled BOOLEAN DEFAULT false"))
        conn.execute(text("ALTER TABLE visit_types ADD COLUMN IF NOT EXISTS ssn_ticket_cents INTEGER DEFAULT 0"))
        conn.execute(text("ALTER TABLE visit_types ADD COLUMN IF NOT EXISTS requires_prescription BOOLEAN DEFAULT false"))
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS care_regime VARCHAR(20) DEFAULT 'private'"))
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS quoted_price_cents INTEGER DEFAULT 0"))
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS hold_expires_at TIMESTAMP"))
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS source VARCHAR(40) DEFAULT 'operator'"))
        conn.execute(text("ALTER TABLE calls ADD COLUMN IF NOT EXISTS ai_intent VARCHAR(60)"))
        conn.execute(text("ALTER TABLE calls ADD COLUMN IF NOT EXISTS ai_sentiment VARCHAR(30)"))
        conn.execute(text("ALTER TABLE calls ADD COLUMN IF NOT EXISTS ai_confidence INTEGER"))
        conn.execute(text("ALTER TABLE calls ADD COLUMN IF NOT EXISTS ai_last_summary TEXT"))
        conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS journey_id VARCHAR(36)"))
        conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS patient_id INTEGER"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_sessions_journey_id ON chat_sessions(journey_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_sessions_patient_id ON chat_sessions(patient_id)"))
        conn.execute(text("UPDATE chat_sessions SET journey_id=id WHERE journey_id IS NULL OR journey_id=''"))
        conn.execute(text("UPDATE visit_types SET private_price_cents = CASE code WHEN 'CARD' THEN 12000 WHEN 'DERM' THEN 10000 WHEN 'ECO' THEN 9000 WHEN 'CTRL' THEN 6500 WHEN 'URG' THEN 14000 ELSE private_price_cents END WHERE code IN ('CARD','DERM','ECO','CTRL','URG') AND COALESCE(private_price_cents,0)=0"))
        conn.execute(text("UPDATE visit_types SET ssn_enabled=true, ssn_ticket_cents=3600 WHERE code IN ('CARD','DERM','ECO','CTRL') AND COALESCE(ssn_ticket_cents,0)=0"))
        conn.execute(text("UPDATE visit_types SET requires_prescription=true WHERE code IN ('ECO','URG')"))
    from app.db.database import SessionLocal
    from app.services.runtime_settings import load_overrides
    db = SessionLocal()
    try:
        load_overrides(db)
        # Gli account demo di accesso sono indipendenti dal dataset pazienti/appuntamenti.
        # Questo evita che un seed parziale o DEMO_DATA_ENABLED=false impediscano il collaudo.
        if settings.DEMO_LOGIN_USERS_ENABLED:
            from app.services.demo_staff import ensure_demo_staff
            result = ensure_demo_staff(db)
            logger.info("Account demo verificati: %s", result)
        from app.services.previsit_service import ensure_default_templates
        ensure_default_templates(db)
        # Primo avvio: trasforma il catalogo prestazioni esistente in tipologie visita.
        from app.models.calendar import VisitType
        if db.query(VisitType).count() == 0:
            for idx, name in enumerate((x.strip() for x in settings.CUP_SERVICES.split(",") if x.strip()), start=1):
                db.add(VisitType(code=f"CUP{idx:03d}", name=name, duration_minutes=30, active=True))
            db.commit()
        if settings.DEMO_DATA_ENABLED and settings.DEMO_AUTO_SEED:
            from app.services.demo_data import seed_demo_data
            seed_demo_data(db, force=False)
        # Merge legacy/bootstrap duplicates after all seeders have run.
        from app.services.visit_type_cleanup import merge_duplicate_visit_types
        cleanup = merge_duplicate_visit_types(db)
        if cleanup["merged"]:
            logger.info("Prestazioni duplicate consolidate: %s", cleanup)
    finally:
        db.close()
    # Avvia il listener AMI in background; se Asterisk non è raggiungibile
    # logga l'errore ma non blocca l'avvio del resto dell'applicazione.
    if settings.AMI_LISTENER_ENABLED:
        asyncio.create_task(start_ami_listener())
    else:
        logger.info("AMI listener disabled by configuration")
    asyncio.create_task(handoff_routes.timeout_worker())
    from app.services.reminder_service import reminder_worker
    asyncio.create_task(reminder_worker())
    from app.services.waitlist_service import waitlist_worker
    asyncio.create_task(waitlist_worker())
    from app.services.care_service import care_worker
    asyncio.create_task(care_worker())


@app.get("/api/health")
def health():
    return {"status": "ok", "version": settings.APP_VERSION}
