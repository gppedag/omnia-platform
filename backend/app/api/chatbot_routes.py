"""
Chatbot CUP v1.0.12 omnichannel + Journey + Chatwoot.

Espone:
- chatbot web pubblico con flusso guidato di prenotazione;
- handoff a operatore;
- inbox operatori autenticata;
- webhook Telegram/WhatsApp/Facebook normalizzati sullo stesso router.

Il motore conversazionale supporta un LLM OpenAI-compatible opzionale.
Quando LLM_ENABLED=false o il provider non e' configurato/raggiungibile,
il chatbot mantiene il flusso CUP deterministico come fallback.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import uuid
from pathlib import Path
from datetime import datetime, timedelta, date, time
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role, require_operator_channel, hash_password
from app.services.patient_identity_service import (
    resolve_patient,
    IdentityConflict,
)
from app.config import settings
from app.db.database import get_db
from app.models.booking import Booking
from app.models.calendar import Agenda, AgendaRule, AgendaException, VisitType
from app.models.chat import ChatAttachment, ChatMessage, ChatSession
from app.models.omnichannel import HandoffEvent
from app.services import llm_service, handoff_service
from app.services.channel_service import add_channel_link, send_outbound
from app.services import chatwoot_service
from app.services.asterisk_gateway import originate_operator_call
from app.models.patient import Patient
from app.models.user import User
from app.services.reminder_service import ensure_booking_reminders
from app.services.previsit_service import ensure_previsit_for_booking
from app.services.live_session_service import require_live

router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])

ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".txt"}
ALLOWED_ATTACHMENT_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "application/octet-stream",
}


def _attachment_payload(a: ChatAttachment, public: bool = True) -> dict:
    base = f"/api/chatbot/web/{a.session_id}/attachments/{a.id}" if public else f"/api/chatbot/sessions/{a.session_id}/attachments/{a.id}"
    return {
        "id": a.id,
        "filename": a.original_filename,
        "mime_type": a.mime_type,
        "size_bytes": a.size_bytes,
        "created_at": a.created_at,
        "url": base,
    }


def _safe_original_filename(name: str) -> str:
    cleaned = Path(name or "documento").name.strip()
    cleaned = re.sub(r"[^A-Za-z0-9._() -]", "_", cleaned)
    return cleaned[:255] or "documento"


class WebChatRequest(BaseModel):
    session_id: Optional[str] = None
    text: str = Field(min_length=1, max_length=2000)


class OperatorReply(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def services() -> list[str]:
    return [x.strip() for x in settings.CUP_SERVICES.split(",") if x.strip()]


def _ctx(session: ChatSession) -> dict:
    try:
        return json.loads(session.context_json or "{}")
    except json.JSONDecodeError:
        return {}


def _save_ctx(session: ChatSession, context: dict):
    session.context_json = json.dumps(context, ensure_ascii=False)


def _add(db: Session, session: ChatSession, role: str, content: str):
    db.add(ChatMessage(session_id=session.id, role=role, content=content))


def _yes(text: str) -> bool:
    return text.strip().lower() in {"si", "sì", "yes", "ok", "confermo", "conferma"}


def _no(text: str) -> bool:
    return text.strip().lower() in {"no", "annulla", "annullare", "cancel"}


def _parse_datetime(value: str) -> Optional[datetime]:
    value = value.strip()
    formats = [
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            if dt > datetime.now():
                return dt
        except ValueError:
            pass
    return None


def _resolve_service(text: str) -> Optional[str]:
    """
    OMNIA_SERVICE_NLU_V2

    Il catalogo services() resta la fonte autorevole.

    Supporta:
    - nome esatto;
    - parti del nome;
    - refusi;
    - espressioni naturali comuni;
    - sinonimi orientativi, senza diagnosi.
    """
    from difflib import SequenceMatcher
    import re
    import unicodedata

    available = services()

    raw = (text or "").strip()

    if not raw:
        return None

    # Se l'utente seleziona un numero dalla lista.
    if raw.isdigit():
        i = int(raw) - 1
        if 0 <= i < len(available):
            return available[i]

    def norm(value):
        value = unicodedata.normalize(
            "NFKD",
            str(value).lower()
        )

        value = "".join(
            c for c in value
            if not unicodedata.combining(c)
        )

        value = re.sub(
            r"[^a-z0-9 ]+",
            " ",
            value
        )

        return " ".join(
            value.split()
        )

    query = norm(raw)

    # --------------------------------------------------------
    # 1. MATCH ESATTO / CONTENUTO
    # --------------------------------------------------------

    for svc in available:

        target = norm(svc)

        if query == target:
            return svc

        if query in target:
            return svc

        # Es.:
        # "vorrei una visita cardiologica"
        if target in query:
            return svc


    # --------------------------------------------------------
    # 2. SINONIMI DI LINGUAGGIO NATURALE
    #
    # Non formulano diagnosi.
    # Servono soltanto a orientare verso una prestazione
    # presente realmente nel catalogo.
    # --------------------------------------------------------

    aliases = {
        "cardiolog": (
            "cardiologo",
            "cardiologa",
            "cardiologia",
            "cardiologica",
            "cardiologico",
            "cuore",
            "cardiaco",
            "cardiaca",
        ),

        "ortoped": (
            "ortopedico",
            "ortopedica",
            "ortopedia",
            "ginocchio",
            "spalla",
        ),

        "ocul": (
            "oculista",
            "oculistica",
            "oculistico",
            "vista",
            "occhi",
        ),

        "dermatolog": (
            "dermatologo",
            "dermatologa",
            "dermatologia",
            "dermatologica",
            "pelle",
        ),
    }

    query_tokens = set(query.split())

    for service in available:

        target = norm(service)

        for service_hint, words in aliases.items():

            if service_hint not in target:
                continue

            if any(
                norm(word) in query_tokens
                for word in words
            ):
                return service


    # --------------------------------------------------------
    # 3. FUZZY TOKEN MATCH
    #
    # Confrontiamo parole della frase dell'utente con parole
    # della prestazione.
    #
    # Esempi:
    # cadiologica     -> cardiologica
    # cardioloogicca  -> cardiologica
    # cardiologo      -> cardiologica
    # --------------------------------------------------------

    query_words = [
        w for w in query.split()
        if len(w) >= 5
    ]

    best_service = None
    best_score = 0.0

    for service in available:

        target = norm(service)

        target_words = [
            w for w in target.split()
            if len(w) >= 5
        ]

        # Similarita' frase intera.
        score = SequenceMatcher(
            None,
            query,
            target
        ).ratio()

        # Similarita' fra singole parole.
        for qw in query_words:
            for tw in target_words:

                token_score = SequenceMatcher(
                    None,
                    qw,
                    tw
                ).ratio()

                score = max(
                    score,
                    token_score
                )

        if score > best_score:
            best_score = score
            best_service = service


    # Abbastanza tollerante ai refusi,
    # ma non abbastanza da scegliere servizi casualmente.
    if best_service and best_score >= 0.78:
        return best_service

    return None


def _service_prompt() -> str:
    lines = ["Quale prestazione vuoi prenotare?"]
    lines.extend(f"{i}. {svc}" for i, svc in enumerate(services(), start=1))
    return "\n".join(lines)


def _find_or_create_patient(db: Session, context: dict) -> Patient:
    """
    Tutti i canali devono convergere sul Patient Identity Service.
    Il chatbot non crea piu autonomamente User/Patient.
    """
    try:
        return resolve_patient(
            db,
            full_name=context.get("full_name") or "Paziente",
            email=context.get("email"),
            phone=context.get("phone"),
            fiscal_code=context.get("fiscal_code"),
            source="chatbot",
            create_if_missing=True,
        )
    except IdentityConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "IDENTITY_VERIFICATION_REQUIRED",
                "message": str(exc),
            },
        )

def _patient_booking_url() -> str:
    path = (getattr(settings, "PATIENT_BOOKING_PATH", "") or "/patient-portal.html?view=booking").strip()
    base = (getattr(settings, "CUP_PUBLIC_BASE_URL", "") or "").rstrip("/")
    return (base + path) if base and path.startswith("/") else path


def _booking_mode_reply() -> str:
    mode = getattr(settings, "BOOKING_MODE", "internal")
    if mode == "external":
        name = (getattr(settings, "EXTERNAL_BOOKING_NAME", "Gestionale prenotazioni") or "Gestionale prenotazioni").strip()
        url = (getattr(settings, "EXTERNAL_BOOKING_URL", "") or "").strip()
        if url:
            return (
                f"Per le prenotazioni questo centro utilizza {name}. "
                f"Puoi accedere qui: {url}. "
                "Io resto disponibile per informazioni, documenti e assistenza; se vuoi puoi anche chiedere OPERATORE."
            )
        return (
            f"Per le prenotazioni questo centro utilizza {name}, ma il collegamento non è ancora configurato. "
            "Posso comunque aiutarti con informazioni e documenti oppure inoltrarti a un OPERATORE."
        )
    if mode == "chatbot_only":
        return (
            "Il servizio di prenotazione non è gestito direttamente da questo assistente. "
            "Posso aiutarti con informazioni, raccogliere documenti e metterti in contatto con un OPERATORE."
        )
    return ""


def _service_visit_type(db: Session, service: str) -> Optional[VisitType]:
    low=(service or "").strip().lower()
    rows=db.query(VisitType).filter(VisitType.active==True).order_by(VisitType.id).all()
    exact=[row for row in rows if row.name.strip().lower()==low]
    for row in exact:
        if any(a.active for a in row.agendas): return row
    if exact: return exact[0]
    partial=[row for row in rows if low in row.name.lower() or row.name.lower() in low]
    for row in partial:
        if any(a.active for a in row.agendas): return row
    if partial: return partial[0]
    return None


def _free_slots_for_agenda(db: Session, agenda: Agenda, vt: VisitType, day: date) -> list[dict]:
    duration=vt.duration_minutes or agenda.slot_minutes or 30
    rules=[r for r in agenda.rules if r.active and r.weekday==day.weekday() and (not r.valid_from or r.valid_from<=day) and (not r.valid_to or r.valid_to>=day)]
    blocked=db.query(AgendaException).filter(AgendaException.agenda_id==agenda.id,AgendaException.date==day,AgendaException.kind=='blocked').all()
    start_day=datetime.combine(day,time.min); end_day=start_day+timedelta(days=1)
    bookings=db.query(Booking).filter(Booking.agenda_id==agenda.id,Booking.status!='cancelled',Booking.scheduled_at<end_day).filter((Booking.end_at>start_day)|((Booking.end_at==None)&(Booking.scheduled_at>=start_day))).all()
    out=[]
    for r in rules:
        cur=datetime.combine(day,r.start_time); limit=datetime.combine(day,r.end_time)
        while cur+timedelta(minutes=duration)<=limit:
            finish=cur+timedelta(minutes=duration)
            if cur <= datetime.now()+timedelta(minutes=5):
                cur += timedelta(minutes=agenda.slot_minutes or 15); continue
            conflict=any((b.end_at or (b.scheduled_at+timedelta(minutes=agenda.slot_minutes or 15)))>cur and b.scheduled_at<finish for b in bookings)
            conflict=conflict or any((ex.start_time is None or datetime.combine(day,ex.start_time)<finish) and (ex.end_time is None or datetime.combine(day,ex.end_time)>cur) for ex in blocked)
            if not conflict:
                out.append({"agenda_id":agenda.id,"visit_type_id":vt.id,"doctor_id":agenda.doctor_id,"start":cur.isoformat(),"end":finish.isoformat(),"agenda_name":agenda.name,"doctor_name":agenda.doctor.full_name if agenda.doctor else ""})
            cur += timedelta(minutes=agenda.slot_minutes or 15)
    return out


def _suggest_slots(db: Session, service: str, limit: int = 3, horizon_days: int = 30, exclude_starts: set[str] | None = None) -> list[dict]:
    vt=_service_visit_type(db,service)
    if not vt: return []
    agendas=db.query(Agenda).filter(Agenda.active==True).order_by(Agenda.id).all()
    agendas=[a for a in agendas if (not a.visit_types or any(x.id==vt.id for x in a.visit_types))]
    candidates=[]
    exclude_starts=exclude_starts or set()
    today=datetime.now().date()
    for offset in range(horizon_days+1):
        day=today+timedelta(days=offset)
        for agenda in agendas:
            candidates.extend(x for x in _free_slots_for_agenda(db,agenda,vt,day) if x["start"] not in exclude_starts)
        candidates.sort(key=lambda x:x["start"])
        if len(candidates)>=limit: break
    # Favorisce alternative distribuite, evitando tre slot consecutivi quando possibile.
    chosen=[]
    seen_days=set()
    for slot in candidates:
        d=slot["start"][:10]
        if d not in seen_days or len(chosen)>=2:
            chosen.append(slot); seen_days.add(d)
        if len(chosen)>=limit: break
    if len(chosen)<min(limit,len(candidates)):
        for slot in candidates:
            if slot not in chosen: chosen.append(slot)
            if len(chosen)>=limit: break
    return chosen[:limit]


def _slots_prompt(slots: list[dict]) -> str:
    if not slots:
        return "Al momento non trovo slot liberi nei prossimi 30 giorni. Posso metterti in contatto con un OPERATORE o registrare la richiesta in lista d'attesa."
    lines=["Ho verificato l'agenda in tempo reale. Posso proporti questi appuntamenti:"]
    for i,slot in enumerate(slots,1):
        dt=datetime.fromisoformat(slot["start"])
        who=f" · {slot['doctor_name']}" if slot.get('doctor_name') else ""
        lines.append(f"{i}. {dt.strftime('%d/%m/%Y alle %H:%M')}{who}")
    lines.append("Rispondi con il numero dell’appuntamento scelto. Se nessuno va bene scrivi ALTRE PROPOSTE.")
    return "\n".join(lines)


def _slot_still_free(db: Session, slot: dict) -> bool:
    start=datetime.fromisoformat(slot["start"]); end=datetime.fromisoformat(slot["end"])
    conflict=db.query(Booking).filter(Booking.agenda_id==slot["agenda_id"],Booking.status!='cancelled',Booking.scheduled_at<end).filter((Booking.end_at>start)|((Booking.end_at==None)&(Booking.scheduled_at>=start))).first()
    return conflict is None and start > datetime.now()


def _create_booking(db: Session, session: ChatSession, context: dict) -> Booking:
    patient = _find_or_create_patient(db, context)
    slot=context["selected_slot"]
    if not _slot_still_free(db,slot):
        raise ValueError("slot_unavailable")
    vt=db.get(VisitType,slot.get("visit_type_id")); agenda=db.get(Agenda,slot.get("agenda_id"))
    start=datetime.fromisoformat(slot["start"]); end=datetime.fromisoformat(slot["end"])
    booking = Booking(patient_id=patient.id,service_name=context["service"],scheduled_at=start,end_at=end,agenda_id=slot.get("agenda_id"),visit_type_id=slot.get("visit_type_id"),status="confirmed",priority="normal",notes=f"Prenotazione confermata via chatbot - sessione {session.id}")
    if agenda and agenda.doctor: booking.doctors=[agenda.doctor]
    db.add(booking); db.flush()
    ensure_booking_reminders(db,booking,include_confirmation=True)
    ensure_previsit_for_booking(db,booking)
    return booking


def _new_session(db: Session, channel: str = "web", sender_id: str = "") -> ChatSession:
    session = ChatSession(
        id=str(uuid.uuid4()),
        channel=channel,
        sender_id=sender_id or None,
        status="bot",
        context_json=json.dumps(
            {
                "step": "llm",
                "flow": "welcome",
                "intent": None,
                "stage": "understand",
                "owner": "ai",
            },
            ensure_ascii=False,
        ),
    )
    db.add(session)
    db.flush()
    # Registra anche il canale web nel Journey, non solo nella ChatSession.
    add_channel_link(db, session.id, channel, sender_id or session.id, "Chatbot web" if channel == "web" else "", {"source": "chatbot"})
    return session



# ============================================================
# OMNIA_CONVERSATION_FLOW_V3
#
# Principio:
#
# LLM          -> comprensione linguistica (successivamente)
# Flow V3      -> governa la conversazione
# API / DB     -> eseguono azioni reali
#
# Il flow deve essere sensato anche senza LLM.
# ============================================================

def _omnia_flow_v3(
    db: Session,
    session: ChatSession,
    context: dict,
    text: str,
):
    low = (text or "").strip().lower()

    if not low:
        return None


    def finish(reply: str):
        _save_ctx(session, context)
        return reply


    # --------------------------------------------------------
    # STATO BASE
    # --------------------------------------------------------

    context.setdefault("flow", "conversation")
    context.setdefault("stage", "welcome")
    context.setdefault("intent", None)
    context.setdefault("owner", "ai")


    # --------------------------------------------------------
    # HANDOFF UMANO
    # Priorita assoluta.
    # --------------------------------------------------------

    if any(
        value in low
        for value in (
            "operatore",
            "persona",
            "persona vera",
            "umano",
            "assistenza umana",
            "parlare con qualcuno",
        )
    ):
        context["intent"] = "human_handoff"
        context["stage"] = "handoff"
        context["owner"] = "handoff"
        context["step"] = "handoff"

        handoff_service.create_request(
            db,
            session,
            "Richiesta esplicita utente",
            source=session.channel or "web",
        )

        return finish(
            "Certo. Sto trasferendo la conversazione "
            "a un operatore CUP. "
            "L'operatore vedra anche quanto ci siamo "
            "gia detti, quindi non dovrai ricominciare da capo."
        )


    # --------------------------------------------------------
    # SESSIONE GIA PASSATA A OPERATORE
    # --------------------------------------------------------

    if session.status == "handoff":
        return finish(
            "Il tuo messaggio e stato ricevuto. "
            "Un operatore CUP potra risponderti "
            "nella stessa conversazione."
        )


    stage = context.get("stage")


    # ========================================================
    # 1. SERVICE DISCOVERY
    #
    # Esempio:
    # "devo controllare il ginocchio"
    # ========================================================

    if stage == "service_discovery":

        if any(
            value in low
            for value in (
                "ho la prescrizione",
                "ho una prescrizione",
                "ho gia una prescrizione",
                "ho già una prescrizione",
                "ho la mia prescrizione",
                "ho l'impegnativa",
                "ho gia l'impegnativa",
                "ho già l'impegnativa",
                "ho impegnativa",
                "so cosa devo fare",
            )
        ):
            context["stage"] = "booking_service"

            return finish(
                "Perfetto. Dimmi cosa c'e scritto "
                "sulla prescrizione o il nome della "
                "visita o dell'esame."
            )


        if any(
            value in low
            for value in (
                "orientarmi",
                "non lo so",
                "non so",
                "non ho prescrizione",
                "non ho la prescrizione",
            )
        ):
            context["stage"] = "service_discovery_clarify"

            query = context.get("service_query") or ""

            return finish(
                "Va bene. Posso aiutarti a orientarti "
                "tra le prestazioni disponibili nella struttura, "
                "ma non posso stabilire quale visita o esame "
                "sia clinicamente necessario. "
                + (
                    f"Hai indicato: {query}. "
                    if query else ""
                )
                + "Sai almeno se cerchi una visita specialistica "
                "oppure un esame diagnostico?"
            )


        return finish(
            "Hai gia una prescrizione o sai quale "
            "visita o esame devi fare?"
        )


    if stage == "service_discovery_clarify":

        context["service_query_detail"] = text.strip()

        return finish(
            "Perfetto. Ho registrato questa indicazione. "
            "Per evitare di suggerirti una prestazione clinicamente "
            "non appropriata, posso cercare nel catalogo della "
            "struttura oppure passarti un operatore CUP."
        )


    # ========================================================
    # 2. PRENOTAZIONE - IDENTIFICAZIONE PRESTAZIONE
    # ========================================================

    if stage == "booking_service":

        service = _resolve_service(text)

        if not service:
            context["service_query"] = text.strip()

            return finish(
                "Non riesco ancora a identificare con certezza "
                "la prestazione. Puoi scrivere il nome riportato "
                "sulla prescrizione, ad esempio "
                "'visita cardiologica' o il nome dell'esame?"
            )

        context["service"] = service
        context["intent"] = "booking"
        context["stage"] = "booking_regime"

        return finish(
            f"Perfetto, ho trovato: {service}. "
            "Vuoi effettuare la prestazione tramite SSN "
            "oppure privatamente?"
        )


    # ========================================================
    # 3. REGIME
    # ========================================================

    if stage == "booking_regime":

        if any(
            value in low
            for value in (
                "ssn",
                "servizio sanitario",
                "mutua",
                "impegnativa",
            )
        ):
            context["regime"] = "ssn"

        elif any(
            value in low
            for value in (
                "privato",
                "privatamente",
                "solvente",
            )
        ):
            context["regime"] = "private"

        else:
            return finish(
                "Preferisci prenotare tramite SSN "
                "oppure privatamente?"
            )

        context["stage"] = "booking_availability"
        context["action"] = "open_booking"
        context["action_url"] = _patient_booking_url()

        return finish(
            f"Perfetto. Prestazione: {context.get('service')}. "
            "Ora possiamo verificare le disponibilita reali. "
            "Puoi aprire la ricerca degli appuntamenti "
            "oppure chiedermi assistenza."
        )


    # ========================================================
    # 4. GESTIONE PRENOTAZIONE ESISTENTE
    # ========================================================

    if stage == "booking_manage_action":

        if any(
            value in low
            for value in (
                "consultare",
                "vedere",
                "visualizzare",
                "controllare",
            )
        ):
            context["booking_manage_action"] = "view"

        elif any(
            value in low
            for value in (
                "modificare",
                "spostare",
                "cambiare",
            )
        ):
            context["booking_manage_action"] = "modify"

        elif any(
            value in low
            for value in (
                "annullare",
                "disdire",
                "cancellare",
            )
        ):
            context["booking_manage_action"] = "cancel"

        else:
            return finish(
                "Vuoi consultare, modificare "
                "o annullare un appuntamento?"
            )

        context["stage"] = "booking_manage_portal"
        context["action"] = "open_patient_area"
        context["action_url"] = "/patient-portal.html"

        return finish(
            "Va bene. Apri l'Area Paziente per "
            "gestire l'appuntamento in sicurezza. "
            "Se preferisci posso passarti un operatore CUP."
        )


    # ========================================================
    # 5. INFORMAZIONI PRESTAZIONE
    # ========================================================

    if stage == "service_info_service":

        service = _resolve_service(text)

        if not service:
            return finish(
                "Quale visita o esame ti interessa? "
                "Scrivi il nome della prestazione."
            )

        context["service"] = service
        context["stage"] = "service_info_topic"

        return finish(
            f"Ho trovato: {service}. "
            "Cosa vuoi sapere? Posso aiutarti con "
            "preparazione, durata, sedi o modalita di accesso."
        )


    if stage == "service_info_topic":

        context["info_topic"] = text.strip()

        # Per ora non inventiamo informazioni cliniche.
        return finish(
            f"Ho capito che vuoi informazioni su "
            f"{context.get('service')}. "
            "Per le indicazioni cliniche e di preparazione "
            "useremo esclusivamente la scheda ufficiale "
            "della struttura. Se vuoi, posso anche "
            "passarti un operatore CUP."
        )


    # ========================================================
    # 6. INFORMAZIONI STRUTTURA
    # ========================================================

    if stage == "facility_info_topic":

        if "orar" in low:
            return finish(
                "La struttura e aperta dal lunedi al venerdi "
                "dalle 8:00 alle 20:00 e il sabato "
                "dalle 8:00 alle 13:00."
            )

        if any(
            value in low
            for value in (
                "dove",
                "indirizzo",
                "arrivare",
                "parcheggio",
            )
        ):
            return finish(
                "La struttura demo si trova in Via Salute 45, "
                "20100 Milano. E disponibile anche il parcheggio."
            )

        if any(
            value in low
            for value in (
                "contatti",
                "telefono",
                "email",
            )
        ):
            return finish(
                "Posso aiutarti con i contatti della struttura. "
                "Se invece hai bisogno di assistenza su una "
                "prenotazione posso passarti direttamente "
                "un operatore CUP."
            )

        return finish(
            "Ti servono gli orari, l'indirizzo, "
            "le indicazioni per arrivare oppure i contatti?"
        )


    # ========================================================
    # CLASSIFICAZIONE MACRO-INTENT
    # ========================================================


    # --------------------------------------------------------
    # GESTIONE PRENOTAZIONE
    # prima di nuova prenotazione.
    # --------------------------------------------------------

    if any(
        value in low
        for value in (
            "gestire una prenotazione",
            "mia prenotazione",
            "mio appuntamento",
            "le mie prenotazioni",
            "annullare prenotazione",
            "disdire prenotazione",
            "modificare prenotazione",
            "spostare appuntamento",
        )
    ):
        context["intent"] = "booking_manage"
        context["stage"] = "booking_manage_action"
        context["flow"] = "booking_manage"

        return finish(
            "Certo. Vuoi consultare, modificare "
            "o annullare un appuntamento?"
        )


    # --------------------------------------------------------
    # NUOVA PRENOTAZIONE
    # --------------------------------------------------------

    if any(
        value in low
        for value in (
            "prenotare",
            "prenota",
            "nuova prenotazione",
            "nuovo appuntamento",
            "vorrei una visita",
            "vorrei fare una visita",
            "vorrei fare un esame",
            "prenotare visita",
            "prenotare esame",
        )
    ):
        context["intent"] = "booking"
        context["stage"] = "booking_service"
        context["flow"] = "booking"

        # Proviamo subito a riconoscere una prestazione.
        service = _resolve_service(text)

        if service:
            context["service"] = service
            context["stage"] = "booking_regime"

            return finish(
                f"Ho trovato: {service}. "
                "Vuoi prenotarla tramite SSN "
                "oppure privatamente?"
            )

        return finish(
            "Certamente. Quale visita o esame "
            "devi prenotare?"
        )


    # --------------------------------------------------------
    # INFORMAZIONI PRESTAZIONE
    # --------------------------------------------------------

    if any(
        value in low
        for value in (
            "informazioni su una prestazione",
            "informazioni sulla visita",
            "informazioni sull'esame",
            "preparazione",
            "digiuno",
            "quanto dura",
            "a cosa serve",
        )
    ):
        context["intent"] = "service_info"
        context["stage"] = "service_info_service"
        context["flow"] = "information"

        service = _resolve_service(text)

        if service:
            context["service"] = service
            context["stage"] = "service_info_topic"

            return finish(
                f"Ho trovato: {service}. "
                "Cosa vuoi sapere? Preparazione, "
                "durata, sedi o modalita di accesso?"
            )

        return finish(
            "Certo. Su quale visita o esame "
            "vuoi informazioni?"
        )


    # --------------------------------------------------------
    # STRUTTURA
    # --------------------------------------------------------

    if any(
        value in low
        for value in (
            "orari",
            "dove siete",
            "indirizzo",
            "come arrivare",
            "parcheggio",
            "contatti",
        )
    ):
        context["intent"] = "facility_info"
        context["stage"] = "facility_info_topic"
        context["flow"] = "information"

        # Riesegue lo stesso messaggio nel nuovo stage.
        if "orar" in low:
            return finish(
                "La struttura e aperta dal lunedi al venerdi "
                "dalle 8:00 alle 20:00 e il sabato "
                "dalle 8:00 alle 13:00."
            )

        if any(
            value in low
            for value in (
                "dove",
                "indirizzo",
                "arrivare",
                "parcheggio",
            )
        ):
            return finish(
                "La struttura demo si trova in Via Salute 45, "
                "20100 Milano. E disponibile anche il parcheggio."
            )

        return finish(
            "Ti servono orari, indirizzo, "
            "indicazioni per arrivare oppure contatti?"
        )


    # --------------------------------------------------------
    # PRESTAZIONE SCRITTA DIRETTAMENTE
    #
    # "cardiologica"
    # --------------------------------------------------------

    service = _resolve_service(text)

    if service:
        context["service"] = service
        context["intent"] = "service_found"
        context["stage"] = "service_found"

        return finish(
            f"Ho trovato la prestazione: {service}. "
            "Vuoi prenotarla oppure vuoi informazioni?"
        )


    # --------------------------------------------------------
    # ESPRESSIONE NATURALE / BISOGNO GENERICO
    #
    # "devo controllare il ginocchio"
    # "devo fare un controllo"
    # --------------------------------------------------------

    if any(
        value in low
        for value in (
            "devo controllare",
            "devo fare",
            "mi serve",
            "ho bisogno",
            "vorrei controllare",
            "vorrei fare un controllo",
        )
    ):
        context["intent"] = "service_discovery"
        context["stage"] = "service_discovery"
        context["flow"] = "service_discovery"
        context["service_query"] = text.strip()

        return finish(
            "Certo. Posso aiutarti a orientarti. "
            "Hai gia una prescrizione o sai quale "
            "visita o esame devi fare?"
        )


    # --------------------------------------------------------
    # SALUTO
    # --------------------------------------------------------

    if low in (
        "ciao",
        "buongiorno",
        "buonasera",
        "salve",
    ):
        context["stage"] = "welcome"

        return finish(
            "Ciao. Come posso aiutarti? "
            "Puoi chiedermi di prenotare una visita o un esame, "
            "avere informazioni oppure gestire "
            "un appuntamento gia esistente."
        )


    # Nessuna decisione deterministica:
    # il legacy/LLM puo eventualmente intervenire.
    return None


def process_message(db: Session, session: ChatSession, text: str) -> str:
    context = _ctx(session)
    step = context.get("step", "llm")
    low = text.strip().lower()

    # OMNIA_FLOW_V3_GATE
    v3_reply = _omnia_flow_v3(
        db,
        session,
        context,
        text,
    )

    if v3_reply is not None:
        return v3_reply

    # ========================================================
    # OMNIA_CONVERSATION_STATE_V2
    #
    # LLM = comprensione e linguaggio.
    # Context = stato deterministico del percorso.
    # ========================================================

    context.setdefault("flow", "conversation")
    context.setdefault("stage", "understand")
    context.setdefault("owner", "ai")

    # Classificazione deterministica dei macro intent.
    # Non sostituisce l'LLM: serve a governare il workflow.
    if any(
        k in low
        for k in (
            "annulla prenotazione",
            "disdici",
            "sposta appuntamento",
            "modifica appuntamento",
            "cambia appuntamento",
            "le mie prenotazioni",
        )
    ):
        context["intent"] = "booking_manage"
        context["stage"] = "manage_booking"

    elif any(
        k in low
        for k in (
            "orari",
            "dove siete",
            "dove si trova",
            "indirizzo",
            "parcheggio",
            "come arrivare",
            "sede",
            "contatti",
        )
    ):
        context["intent"] = "facility_info"
        context["stage"] = "information"

    elif any(
        k in low
        for k in (
            "referto",
            "referti",
            "area paziente",
        )
    ):
        context["intent"] = "patient_area"
        context["stage"] = "patient_area"

    elif any(
        k in low
        for k in (
            "preparazione",
            "digiuno",
            "quanto dura",
            "a cosa serve",
            "informazioni sulla",
            "informazioni su",
        )
    ):
        context["intent"] = "service_info"
        context["stage"] = "information"

    if any(k in low for k in ("operatore", "persona", "umano", "assistenza umana")):
        context["step"] = "handoff"
        context["intent"] = "human_handoff"
        context["stage"] = "handoff"
        context["owner"] = "handoff"
        handoff_service.create_request(db, session, "Richiesta esplicita utente", source=session.channel or "web")
        _save_ctx(session, context)
        return (
            "Ho inoltrato la conversazione a un operatore. "
            "Lo storico della chat e i documenti già caricati rimangono disponibili nella stessa conversazione."
        )

    if session.status == "handoff":
        return "Messaggio ricevuto. Un operatore potrà risponderti da questa conversazione."

    booking_mode = getattr(settings, "BOOKING_MODE", "internal")
    internal_booking_steps = {"collect_name", "collect_email", "collect_phone", "collect_service", "offer_slots", "confirm", "ask_document_upload", "complete"}
    # v1.0.29: la prenotazione non viene piu eseguita nella chat. Anche le
    # vecchie sessioni eventualmente rimaste in uno step di booking vengono
    # riportate al dialogo informativo e indirizzate al modulo Prenota.
    if step in internal_booking_steps:
        context.clear()
        context["step"] = "llm"
        step = "llm"
        _save_ctx(session, context)

    # La chat parte in modalita' LLM. Il flusso prenotazione strutturato
    # rimane disponibile quando l'utente chiede esplicitamente di prenotare.
    if step == "llm":
        # ----------------------------------------------------
        # GESTIONE PRENOTAZIONE ESISTENTE
        # ----------------------------------------------------

        if (
            context.get("intent") == "booking_manage"
            and context.get("stage") == "manage_booking"
        ):
            context["action"] = "open_patient_area"
            context["action_url"] = "/patient-portal.html"

            _save_ctx(session, context)

            return (
                "Certo. Posso aiutarti a gestire una prenotazione gia esistente. "
                "Dall'Area Paziente puoi consultare i tuoi appuntamenti, "
                "modificarli o annullarli. "
                "Se preferisci, posso anche passarti un operatore."
            )


        # ----------------------------------------------------
        # BOOKING CONVERSAZIONALE GUIDATO
        # ----------------------------------------------------

        booking_request = any(
            k in low
            for k in (
                "prenota",
                "prenotazione",
                "nuova prenotazione",
                "prenotare",
                "appuntamento",
                "vorrei fare una visita",
                "vorrei fare un esame",
            )
        )

        # OMNIA_INTENT_PRIORITY_V1
        #
        # "prenotazione" compare anche nelle richieste
        # di modifica/disdetta. Non deve quindi
        # trasformare booking_manage in una nuova booking.
        if (
            booking_request
            and context.get("intent") not in (
                "booking_manage",
                "patient_area",
                "facility_info",
                "service_info",
                "human_handoff",
            )
        ):
            context["intent"] = "booking"
            context["stage"] = "service_resolution"
            context["flow"] = "booking"

        if (
            context.get("intent") == "booking"
            and context.get("stage") == "service_resolution"
        ):
            service = _resolve_service(text)

            if service:
                url = _patient_booking_url()

                context["service"] = service
                context["stage"] = "availability"
                context["action"] = "open_booking"
                context["action_url"] = url

                _save_ctx(session, context)

                return (
                    f"Ho identificato la prestazione: {service}. "
                    "Ora possiamo verificare le disponibilita reali. "
                    f"Apri Prenota per scegliere data, orario e regime: {url}"
                )

            _save_ctx(session, context)

            return (
                "Certamente. Ti aiuto io. "
                "Quale visita o esame devi prenotare?"
            )
        # Lo stato viene salvato anche quando la risposta
        # sara generata dall'LLM.
        _save_ctx(session, context)

        if llm_service.enabled():
            try:
                history = [{"role": m.role, "content": m.content} for m in session.messages[:-1]]
                reply, handoff = llm_service.reply(history, text, db=db)
                if handoff:
                    context["step"] = "handoff"
                    handoff_service.create_request(db, session, "Handoff richiesto dal modello LLM", source=session.channel or "web")
                _save_ctx(session, context)
                return reply
            except Exception:
                logger.exception(
                    "LLM chatbot error session=%s",
                    getattr(session, "id", None),
                )
        if booking_mode != "internal":
            return (
                "Posso aiutarti con informazioni, documenti e assistenza. "
                + ("Scrivi PRENOTAZIONE per accedere al gestionale del centro, oppure OPERATORE per parlare con una persona." if booking_mode == "external" else "Scrivi OPERATORE per parlare con una persona.")
            )
        return (
            "Posso aiutarti con informazioni CUP, documenti e assistenza. "
            f"Per prenotare usa la funzione Prenota del sito: {_patient_booking_url()} . "
            "Scrivi OPERATORE se vuoi parlare con una persona."
        )

    if step == "collect_name":
        context["full_name"] = text.strip()
        context["step"] = "collect_email"
        reply = "Grazie. Qual è la tua email?"

    elif step == "collect_email":
        email = text.strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return "L'indirizzo email non sembra valido. Inseriscilo nel formato nome@dominio.it."
        context["email"] = email
        context["step"] = "collect_phone"
        reply = "Indica un numero di telefono, oppure scrivi SALTA."

    elif step == "collect_phone":
        context["phone"] = "" if low == "salta" else text.strip()
        context["step"] = "collect_service"
        reply = _service_prompt()

    elif step == "collect_service":
        service = _resolve_service(text)
        if not service:
            return "Non riconosco la prestazione.\n" + _service_prompt()
        context["service"] = service
        slots=_suggest_slots(db,service,3)
        context["offered_slots"] = slots
        context["step"] = "offer_slots"
        reply = _slots_prompt(slots)

    elif step == "offer_slots":
        if "altre" in low:
            excluded=set(context.get("excluded_slots") or [])
            excluded.update(x.get("start") for x in (context.get("offered_slots") or []) if x.get("start"))
            slots=_suggest_slots(db,context["service"],3,exclude_starts=excluded)
            if not slots:
                excluded=set(); slots=_suggest_slots(db,context["service"],3)
            context["excluded_slots"] = list(excluded)
            context["offered_slots"] = slots
            reply=_slots_prompt(slots)
        elif text.strip() in {"1","2","3"}:
            idx=int(text.strip())-1; offered=context.get("offered_slots") or []
            if idx >= len(offered): return "Questa scelta non è disponibile. Scegli uno dei numeri proposti."
            slot=offered[idx]
            if not _slot_still_free(db,slot):
                slots=_suggest_slots(db,context["service"],3); context["offered_slots"]=slots
                return "Quello slot è appena stato occupato. Ho aggiornato le disponibilità.\n" + _slots_prompt(slots)
            context["selected_slot"]=slot; context["step"]="confirm"
            dt=datetime.fromisoformat(slot["start"]); who=f" · {slot.get('doctor_name')}" if slot.get('doctor_name') else ""
            reply=("Riepilogo prenotazione:\n"+f"• Paziente: {context['full_name']}\n"+f"• Prestazione: {context['service']}\n"+f"• Appuntamento: {dt.strftime('%d/%m/%Y %H:%M')}{who}\n"+"Scrivi CONFERMO per prenotare oppure ANNULLA.")
        else:
            return "Scegli uno degli appuntamenti disponibili rispondendo con il relativo numero, oppure scrivi ALTRE PROPOSTE."

    elif step == "confirm":
        if "cambia" in low or "altre proposte" in low:
            slots=_suggest_slots(db,context["service"],3)
            context["offered_slots"]=slots
            context["step"]="offer_slots"
            reply = _slots_prompt(slots)
        elif _no(text):
            context.clear()
            context["step"] = "collect_name"
            reply = "Richiesta annullata. Se vuoi ricominciare, dimmi il tuo nome e cognome."
        elif _yes(text) or "conferma appuntamento" in low:
            try:
                booking = _create_booking(db, session, context)
            except ValueError:
                slots=_suggest_slots(db,context["service"],3); context["offered_slots"]=slots; context["step"]="offer_slots"
                return "Lo slot non è più libero. Ti propongo subito le nuove disponibilità.\n" + _slots_prompt(slots)
            context["booking_id"] = booking.id
            context["step"] = "ask_document_upload"
            reply = (
                f"Prenotazione confermata con numero #{booking.id}. Riceverai anche i promemoria previsti dal centro.\n\n"
                "Devi caricare la ricetta o la richiesta medica per questa prenotazione? "
                "Puoi caricarla adesso oppure scegliere NON ORA."
            )
        else:
            return "Conferma l'appuntamento oppure scegli CAMBIA APPUNTAMENTO o ANNULLA."

    elif step == "ask_document_upload":
        if any(k in low for k in ("carica", "ricetta", "richiesta medica", "sì", "si")):
            context["document_upload_requested"] = True
            context["step"] = "complete"
            reply = (
                "Perfetto. Usa il pulsante di caricamento per allegare la ricetta o la richiesta medica. "
                "Il documento resterà associato alla stessa conversazione e sarà visibile all'operatore CUP."
            )
        elif any(k in low for k in ("non ora", "no", "salta", "dopo")):
            context["document_upload_requested"] = False
            context["step"] = "complete"
            reply = (
                f"Va bene. La prenotazione #{context.get('booking_id', '-')} resta confermata. "
                "Potrai comunque allegare il documento più tardi da questa chat."
            )
        else:
            return "Devi caricare la ricetta o la richiesta medica? Scegli CARICA RICETTA/RICHIESTA oppure NON ORA."

    elif step == "complete":
        if any(k in low for k in ("nuova", "prenota", "prenotazione")):
            context.clear()
            context["step"] = "collect_name"
            reply = "Iniziamo una nuova prenotazione. Qual è il tuo nome e cognome?"
        else:
            reply = (
                f"La prenotazione #{context.get('booking_id', '-')} è confermata. "
                "Scrivi NUOVA PRENOTAZIONE per iniziarne un'altra oppure OPERATORE per assistenza."
            )
    else:
        context["step"] = "collect_name"
        reply = "Ciao! Sono l'assistente CUP. Per iniziare, indicami nome e cognome."

    _save_ctx(session, context)
    return reply


@router.post("/web")
def web_chat(payload: WebChatRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    session = None
    if payload.session_id:
        session = db.query(ChatSession).filter(ChatSession.id == payload.session_id).first()
    if not session:
        session = _new_session(db)

    previous_status = session.status
    _add(db, session, "user", payload.text)

    # Se un operatore ha preso in carico la conversazione, il messaggio
    # cliente viene salvato nella stessa sessione ma l'AI non risponde.
    if session.status == "handoff":
        reply = ""
    else:
        reply = process_message(db, session, payload.text)
        if reply:
            _add(db, session, "assistant", reply)

    db.commit()

    if chatwoot_service.enabled():
        try:
            chatwoot_service.push_message(db, session, payload.text, "user")

            if reply:
                chatwoot_service.push_message(db, session, reply, "assistant")

            if (
                previous_status != "handoff"
                and session.status == "handoff"
                and settings.CHATWOOT_AUTO_SYNC_HANDOFF
            ):
                chatwoot_service.set_status(db, session, "open")

            db.commit()
        except Exception:
            pass
    return {
        "ok": True,
        "session_id": session.id,
        "status": session.status,
        "reply": reply,
        "context": _ctx(session),
    }


@router.post("/web/start")
def start_web_chat(db: Session = Depends(get_db)):
    session = _new_session(db)
    greeting = (
        "Ciao, sono Omnia, l'assistente virtuale AI del Centro Medico. "
        "Posso aiutarti a trovare una visita o un esame, prenotare un appuntamento "
        "oppure darti informazioni sui nostri servizi. "
        "Di cosa hai bisogno?"
    )
    _add(db, session, "assistant", greeting)
    db.commit()
    if chatwoot_service.enabled():
        try:
            chatwoot_service.push_message(db, session, greeting, "assistant")
            db.commit()
        except Exception:
            pass
    return {"session_id": session.id, "status": session.status, "reply": greeting}


@router.get("/web/{session_id}/messages")
def public_messages(session_id: str, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessione non trovata")
    return {
        "session_id": session.id,
        "status": session.status,
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
            for m in session.messages
        ],
        "attachments": [_attachment_payload(a, public=True) for a in session.attachments],
        "context": _ctx(session),
    }


@router.post("/web/{session_id}/attachments")
async def upload_web_attachment(
    session_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessione non trovata")
    if session.status == "closed":
        raise HTTPException(status_code=409, detail="La conversazione è chiusa")

    count = db.query(ChatAttachment).filter(ChatAttachment.session_id == session_id).count()
    if count >= settings.CHAT_MAX_ATTACHMENTS:
        raise HTTPException(status_code=400, detail="Numero massimo di allegati raggiunto")

    original = _safe_original_filename(file.filename or "documento")
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Formato file non consentito")

    mime = (file.content_type or "application/octet-stream").lower()
    if mime not in ALLOWED_ATTACHMENT_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Tipo MIME non consentito")

    data = await file.read(settings.CHAT_MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="File vuoto")
    if len(data) > settings.CHAT_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File troppo grande (massimo 10 MB)")

    session_dir = Path(settings.CHAT_UPLOAD_DIR) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{suffix}"
    path = session_dir / stored
    path.write_bytes(data)

    attachment = ChatAttachment(
        session_id=session_id,
        original_filename=original,
        stored_filename=stored,
        mime_type=mime,
        size_bytes=len(data),
    )
    db.add(attachment)
    _add(db, session, "user", f"Documento allegato: {original}")
    context = _ctx(session)
    if context.get("step") == "ask_document_upload":
        context["document_upload_requested"] = True
        context["document_uploaded"] = True
        context["step"] = "complete"
        _save_ctx(session, context)
        _add(db, session, "assistant", "Documento ricevuto e associato alla prenotazione. Grazie.")
    db.commit()
    db.refresh(attachment)
    if chatwoot_service.enabled():
        try:
            chatwoot_service.push_attachment_note(db, session, attachment)
            db.commit()
        except Exception:
            pass
    return {"ok": True, "attachment": _attachment_payload(attachment, public=True)}


@router.get("/web/{session_id}/attachments/{attachment_id}")
def download_web_attachment(session_id: str, attachment_id: int, db: Session = Depends(get_db)):
    attachment = (
        db.query(ChatAttachment)
        .filter(ChatAttachment.id == attachment_id, ChatAttachment.session_id == session_id)
        .first()
    )
    if not attachment:
        raise HTTPException(status_code=404, detail="Allegato non trovato")
    path = Path(settings.CHAT_UPLOAD_DIR) / session_id / attachment.stored_filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File non disponibile")
    return FileResponse(path, media_type=attachment.mime_type, filename=attachment.original_filename)


@router.get("/status")
def chatbot_runtime_status(
    user=Depends(require_operator_channel("chat")),
):
    active = llm_service.enabled()
    return {
        "llm_enabled": active,
        "configured": bool(settings.LLM_BASE_URL and settings.LLM_MODEL),
        "model": settings.LLM_MODEL if active else None,
        "mode": "hybrid_llm" if active else "deterministic_fallback",
        "training_enabled": bool(getattr(settings, "TRAINING_ENABLED", False)),
    }


@router.get("/sessions")
def operator_sessions(
    db: Session = Depends(get_db),
    user=Depends(require_operator_channel("chat")),
):
    rows = db.query(ChatSession).order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc()).limit(200).all()
    return [
        {
            "id": s.id,
            "channel": s.channel,
            "status": s.status,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "last_message": s.messages[-1].content if s.messages else "",
        }
        for s in rows
    ]


def _remove_session_uploads(session_id: str) -> None:
    path = Path(settings.CHAT_UPLOAD_DIR) / session_id
    try:
        if path.exists():
            shutil.rmtree(path)
    except Exception:
        # La cancellazione DB non deve fallire per un file gia' rimosso o un
        # volume temporaneamente non scrivibile. Gli allegati non saranno piu'
        # referenziati dopo il commit.
        pass


@router.delete("/sessions/{session_id}")
def admin_delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessione non trovata")
    db.delete(session)
    db.commit()
    _remove_session_uploads(session_id)
    return {"ok": True, "deleted": 1, "session_id": session_id}


@router.delete("/sessions")
def admin_clear_demo_history(
    db: Session = Depends(get_db),
    user=Depends(require_role("admin")),
):
    # Cancella esclusivamente la cronologia conversazionale. Le anagrafiche,
    # prenotazioni e gli altri dati CUP non vengono toccati. Le FK collegate
    # alla sessione usano CASCADE/SET NULL secondo il relativo modello.
    sessions = db.query(ChatSession).all()
    ids = [s.id for s in sessions]
    for session in sessions:
        db.delete(session)
    db.commit()
    for session_id in ids:
        _remove_session_uploads(session_id)
    return {"ok": True, "deleted": len(ids)}


@router.get("/sessions/{session_id}/messages")
def operator_messages(
    session_id: str,
    db: Session = Depends(get_db),
    user=Depends(require_operator_channel("chat")),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessione non trovata")
    return {
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at}
            for m in session.messages
        ],
        "attachments": [_attachment_payload(a, public=False) for a in session.attachments],
    }


@router.get("/sessions/{session_id}/attachments/{attachment_id}")
def operator_download_attachment(
    session_id: str,
    attachment_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_operator_channel("chat")),
):
    attachment = (
        db.query(ChatAttachment)
        .filter(ChatAttachment.id == attachment_id, ChatAttachment.session_id == session_id)
        .first()
    )
    if not attachment:
        raise HTTPException(status_code=404, detail="Allegato non trovato")
    path = Path(settings.CHAT_UPLOAD_DIR) / session_id / attachment.stored_filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File non disponibile")
    return FileResponse(path, media_type=attachment.mime_type, filename=attachment.original_filename)


@router.post("/sessions/{session_id}/reply")
def operator_reply(
    session_id: str,
    payload: OperatorReply,
    db: Session = Depends(get_db),
    user=Depends(require_operator_channel("chat")),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessione non trovata")

    state = require_live(
        db,
        session,
    )

    if state["owner"] != "operator":
        raise HTTPException(
            status_code=409,
            detail=(
                "La conversazione LIVE non e in carico "
                "all'operatore."
            ),
        )

    session.status = "handoff"
    _add(db, session, "operator", payload.text)
    if getattr(settings, "TRAINING_ENABLED", False) and getattr(settings, "TRAINING_CAPTURE_CHAT_ENABLED", False):
        try:
            from app.services.training_service import capture_chat_example
            capture_chat_example(db, session, user, payload.text)
        except Exception:
            pass
    db.commit()
    outbound = send_outbound(db, session, payload.text)
    if chatwoot_service.enabled():
        try:
            chatwoot_service.push_message(db, session, payload.text, "operator", private=False)
            db.commit()
        except Exception:
            pass
    return {"ok": True, "outbound": outbound}


@router.post("/sessions/{session_id}/close")
def operator_close(
    session_id: str,
    db: Session = Depends(get_db),
    user=Depends(require_operator_channel("chat")),
):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessione non trovata")
    session.status = "closed"
    if chatwoot_service.enabled():
        try:
            chatwoot_service.set_status(db, session, "resolved")
        except Exception:
            pass
    db.commit()
    return {"ok": True}


async def route_message(channel: str, sender_id: str, text: str, db: Session) -> str:
    session = (
        db.query(ChatSession)
        .filter(ChatSession.channel == channel, ChatSession.sender_id == sender_id, ChatSession.status != "closed")
        .order_by(ChatSession.created_at.desc())
        .first()
    )
    if not session:
        session = _new_session(db, channel=channel, sender_id=sender_id)
    _add(db, session, "user", text)
    reply = process_message(db, session, text)
    _add(db, session, "assistant", reply)
    db.commit()
    return reply


@router.post("/legacy/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    message = payload.get("message", {})
    text = message.get("text", "")
    sender_id = str(message.get("chat", {}).get("id", ""))
    reply = await route_message("telegram", sender_id, text, db)
    return {"ok": True, "reply": reply}


@router.post("/legacy/whatsapp/webhook")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    text = payload.get("text", "")
    sender_id = str(payload.get("from", ""))
    reply = await route_message("whatsapp", sender_id, text, db)
    return {"ok": True, "reply": reply}


@router.post("/legacy/facebook/webhook")
async def facebook_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    entry = (payload.get("entry") or [{}])[0]
    messaging = (entry.get("messaging") or [{}])[0]
    text = messaging.get("message", {}).get("text", "")
    sender_id = str(messaging.get("sender", {}).get("id", ""))
    reply = await route_message("facebook", sender_id, text, db)
    return {"ok": True, "reply": reply}

