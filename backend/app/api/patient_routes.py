from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func

from app.db.database import get_db
from app.models.patient import Patient
from app.models.commerce import PaymentRequest
from app.models.portal import PatientDocument
from app.models.booking import Booking
from app.models.user import User
from app.schemas import PatientCreate, PatientOut
from app.auth import require_role, get_current_user
from pydantic import BaseModel
from typing import Optional

class PatientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    fiscal_code: Optional[str] = None
    notes: Optional[str] = None
    reminder_enabled: Optional[bool] = None
    reminder_channels: Optional[str] = None


class ReminderPreferences(BaseModel):
    enabled: Optional[bool] = None
    channels: Optional[str] = None
    telegram_chat_id: Optional[str] = None

router = APIRouter(prefix="/api/patients", tags=["patients"])


def patient_out(patient: Patient) -> dict:
    user = patient.user
    return {
        "id": patient.id,
        "user_id": patient.user_id,
        "first_name": user.first_name if user else None,
        "last_name": user.last_name if user else None,
        "first_name": user.first_name if user else None,
        "last_name": user.last_name if user else None,
        "first_name": user.first_name if user else None,
        "last_name": user.last_name if user else None,
        "full_name": user.full_name if user else None,
        "email": user.email if user else None,
        "phone": user.phone if user else None,
        "date_of_birth": patient.date_of_birth,
        "fiscal_code": patient.fiscal_code,
        "notes": patient.notes,
        "reminder_enabled": str(patient.reminder_enabled or "true").lower() not in {"false","0","no","off"},
        "reminder_channels": patient.reminder_channels,
        "reminder_telegram_chat_id": patient.reminder_telegram_chat_id,
    }


@router.get("/", response_model=List[PatientOut])
def list_patients(db: Session = Depends(get_db), user=Depends(get_current_user)):
    patients = db.query(Patient).options(joinedload(Patient.user)).order_by(Patient.id.desc()).all()
    return [patient_out(p) for p in patients]


@router.post("/", response_model=PatientOut, status_code=201)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    """
    Crea una nuova anagrafica paziente.

    Modalita':
    - nuova: crea User + Patient nella stessa transazione;
    - legacy: se user_id e' valorizzato collega un User esistente.
    """

    from app.auth import hash_password
    import secrets

    data = payload.model_dump()

    # --------------------------------------------------------
    # Compatibilita' legacy
    # --------------------------------------------------------

    if payload.user_id:

        existing_user = db.get(User, payload.user_id)

        if not existing_user:
            raise HTTPException(
                404,
                "Utente associato non trovato"
            )

        existing_patient = (
            db.query(Patient)
            .filter(Patient.user_id == payload.user_id)
            .first()
        )

        if existing_patient:
            raise HTTPException(
                409,
                "Esiste gia una anagrafica paziente per questo utente"
            )

        patient = Patient(
            user_id=payload.user_id,
            date_of_birth=payload.date_of_birth,
            fiscal_code=(
                payload.fiscal_code.strip().upper()
                if payload.fiscal_code
                else None
            ),
            notes=(
                payload.notes.strip()
                if payload.notes
                else None
            ),
            reminder_enabled=(
                "true"
                if payload.reminder_enabled
                else "false"
            ),
            reminder_channels=(
                payload.reminder_channels.strip()
                if payload.reminder_channels
                else None
            ),
            reminder_telegram_chat_id=(
                payload.reminder_telegram_chat_id
                or None
            ),
            identity_status="reception_verified",
        )

        db.add(patient)
        db.commit()
        db.refresh(patient)
        db.refresh(patient, attribute_names=["user"])

        return patient_out(patient)


    # --------------------------------------------------------
    # Nuova anagrafica completa
    # --------------------------------------------------------

    first_name = (payload.first_name or "").strip()
    last_name = (payload.last_name or "").strip()
    email = (payload.email or "").strip().lower()
    phone = (payload.phone or "").strip() or None
    fiscal_code = (
        (payload.fiscal_code or "")
        .strip()
        .upper()
        or None
    )

    if not first_name:
        raise HTTPException(422, "Nome obbligatorio")

    if not last_name:
        raise HTTPException(422, "Cognome obbligatorio")

    if not email or "@" not in email:
        raise HTTPException(422, "Email obbligatoria e non valida")

    if not fiscal_code:
        raise HTTPException(422, "Codice fiscale obbligatorio")

    if not payload.date_of_birth:
        raise HTTPException(422, "Data di nascita obbligatoria")

    if (
        payload.reminder_channels
        and "telegram" in {
            x.strip().lower()
            for x in payload.reminder_channels.split(",")
            if x.strip()
        }
        and not payload.reminder_telegram_chat_id
    ):
        raise HTTPException(
            422,
            "Telegram non disponibile: il paziente non ha collegato il bot"
        )


    # --------------------------------------------------------
    # Duplicati
    # --------------------------------------------------------

    email_owner = (
        db.query(User)
        .filter(
            func.lower(User.email)
            == email.lower()
        )
        .first()
    )

    if email_owner:
        raise HTTPException(
            409,
            "Email gia associata a un altro utente"
        )

    cf_owner = (
        db.query(Patient)
        .filter(
            func.upper(
                func.trim(Patient.fiscal_code)
            ) == fiscal_code
        )
        .first()
    )

    if cf_owner:
        raise HTTPException(
            409,
            "Codice fiscale gia associato a un altro paziente"
        )


    # --------------------------------------------------------
    # Transazione User + Patient
    # --------------------------------------------------------

    full_name = f"{first_name} {last_name}".strip()

    try:

        user_row = User(
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,

            email=email,
            phone=phone,

            hashed_password=hash_password(
                secrets.token_urlsafe(32)
            ),

            role="patient",

            is_active=True,
            can_chat=True,
            can_phone=True,

            phone_verified=False,
            email_verified=False,

            account_status="active",
            activation_source="reception",
        )

        db.add(user_row)
        db.flush()

        patient = Patient(
            user_id=user_row.id,
            date_of_birth=payload.date_of_birth,
            fiscal_code=fiscal_code,
            notes=(
                payload.notes.strip()
                if payload.notes
                else None
            ),

            reminder_enabled=(
                "true"
                if payload.reminder_enabled
                else "false"
            ),

            reminder_channels=(
                payload.reminder_channels.strip()
                if payload.reminder_channels
                else None
            ),

            reminder_telegram_chat_id=(
                payload.reminder_telegram_chat_id
                or None
            ),

            identity_status="reception_verified",
        )

        db.add(patient)

        db.commit()

        db.refresh(patient)
        db.refresh(
            patient,
            attribute_names=["user"]
        )

        return patient_out(patient)

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise



# CUP_PATIENT_SEARCH_API_V1

@router.get("/search")
def search_patients(
    q: str = Query(default="", max_length=150),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=10, le=100),
    reminder: str = Query(default="all"),
    channel: str = Query(default="all"),
    sort: str = Query(default="name"),
    direction: str = Query(default="asc"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Ricerca/paginazione server-side dell'anagrafica pazienti.

    L'endpoint legacy GET /api/patients/ rimane invariato
    per compatibilita' con booking, dashboard e altri moduli.
    """

    query = (
        db.query(Patient)
        .join(User, Patient.user_id == User.id)
        .options(joinedload(Patient.user))
    )

    term = (q or "").strip()

    if term:
        like = f"%{term}%"

        query = query.filter(
            or_(
                User.full_name.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.email.ilike(like),
                User.phone.ilike(like),
                Patient.fiscal_code.ilike(like),
            )
        )

    reminder = (reminder or "all").lower()

    if reminder == "enabled":
        query = query.filter(
            func.lower(
                func.coalesce(Patient.reminder_enabled, "true")
            ).notin_(["false", "0", "no", "off"])
        )

    elif reminder == "disabled":
        query = query.filter(
            func.lower(
                func.coalesce(Patient.reminder_enabled, "true")
            ).in_(["false", "0", "no", "off"])
        )

    channel = (channel or "all").lower()

    if channel != "all":
        query = query.filter(
            func.lower(
                func.coalesce(Patient.reminder_channels, "")
            ).like(f"%{channel}%")
        )

    total = query.count()

    direction = (direction or "asc").lower()
    sort = (sort or "name").lower()

    sort_columns = {
        "email": User.email,
        "phone": User.phone,
        "fiscal_code": Patient.fiscal_code,
        "created_at": Patient.created_at,
    }

    if sort == "name":

        # Ordinamento anagrafico CUP:
        # COGNOME -> NOME -> ID.
        if direction == "desc":
            query = query.order_by(
                func.lower(
                    func.coalesce(User.last_name, "")
                ).desc(),
                func.lower(
                    func.coalesce(User.first_name, "")
                ).desc(),
                Patient.id.desc()
            )
        else:
            query = query.order_by(
                func.lower(
                    func.coalesce(User.last_name, "")
                ).asc(),
                func.lower(
                    func.coalesce(User.first_name, "")
                ).asc(),
                Patient.id.asc()
            )

    else:

        column = sort_columns.get(
            sort,
            User.full_name
        )

        if direction == "desc":
            query = query.order_by(
                column.desc().nullslast(),
                Patient.id.desc()
            )
        else:
            query = query.order_by(
                column.asc().nullslast(),
                Patient.id.asc()
            )

    offset = (page - 1) * page_size

    rows = (
        query
        .offset(offset)
        .limit(page_size)
        .all()
    )

    pages = max(
        1,
        (total + page_size - 1) // page_size
    )

    return {
        "items": [patient_out(p) for p in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "has_previous": page > 1,
        "has_next": page < pages,
    }


@router.get("/count")
def count_patients(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return {
        "total": db.query(func.count(Patient.id)).scalar() or 0
    }



# CUP_PATIENT_HISTORY_API_V1

@router.get("/{patient_id}/history")
def patient_history(
    patient_id: int,
    limit: int = Query(default=200, ge=20, le=500),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Fascicolo operativo / cronologia paziente.

    Aggrega eventi CUP senza duplicare dati clinici:
    - prenotazioni
    - prestazioni completate
    - documenti/referti
    - pagamenti

    Gli "esami effettuati" corrispondono attualmente
    alle Booking con status=completed.
    """

    patient = (
        db.query(Patient)
        .options(joinedload(Patient.user))
        .filter(Patient.id == patient_id)
        .first()
    )

    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Paziente non trovato"
        )

    # -----------------------------------------------------
    # PRENOTAZIONI / PRESTAZIONI
    # -----------------------------------------------------

    bookings = (
        db.query(Booking)
        .filter(
            Booking.patient_id == patient_id
        )
        .order_by(
            Booking.scheduled_at.desc()
        )
        .limit(limit)
        .all()
    )

    # -----------------------------------------------------
    # DOCUMENTI / REFERTI
    # -----------------------------------------------------

    documents = (
        db.query(PatientDocument)
        .filter(
            PatientDocument.patient_id == patient_id
        )
        .order_by(
            PatientDocument.created_at.desc()
        )
        .limit(limit)
        .all()
    )

    # -----------------------------------------------------
    # PAGAMENTI
    # -----------------------------------------------------

    payments = (
        db.query(PaymentRequest)
        .filter(
            PaymentRequest.patient_id == patient_id
        )
        .order_by(
            PaymentRequest.created_at.desc()
        )
        .limit(limit)
        .all()
    )

    now = __import__("datetime").datetime.now()

    timeline = []

    completed_count = 0
    future_count = 0
    cancelled_count = 0

    # -----------------------------------------------------
    # BOOKING -> EVENTI TIMELINE
    # -----------------------------------------------------

    for booking in bookings:

        status = (
            booking.status or "pending"
        ).lower()

        if status == "completed":
            completed_count += 1
            event_kind = "completed"
            event_label = "Prestazione effettuata"

        elif status == "cancelled":
            cancelled_count += 1
            event_kind = "cancelled"
            event_label = "Prenotazione annullata"

        elif (
            booking.scheduled_at
            and booking.scheduled_at >= now
        ):
            future_count += 1
            event_kind = "booking"
            event_label = "Prenotazione"

        else:
            event_kind = "booking"
            event_label = "Prenotazione"

        agenda = getattr(
            booking,
            "agenda",
            None
        )

        visit = getattr(
            booking,
            "visit_type",
            None
        )

        doctor_name = None
        location = None
        agenda_name = None

        if agenda:
            agenda_name = getattr(
                agenda,
                "name",
                None
            )

            location = getattr(
                agenda,
                "location",
                None
            )

            doctor = getattr(
                agenda,
                "doctor",
                None
            )

            if doctor:
                doctor_name = getattr(
                    doctor,
                    "full_name",
                    None
                )

        title = (
            getattr(visit, "name", None)
            or booking.service_name
            or "Prestazione"
        )

        timeline.append({
            "type": "booking",
            "kind": event_kind,
            "label": event_label,

            "date": (
                booking.scheduled_at.isoformat()
                if booking.scheduled_at
                else None
            ),

            "id": booking.id,
            "booking_id": booking.id,

            "title": title,
            "status": status,

            "doctor_name": doctor_name,
            "agenda_name": agenda_name,
            "location": location,

            "regime": (
                getattr(
                    booking,
                    "care_regime",
                    None
                )
                or "private"
            ),

            "price_cents": (
                getattr(
                    booking,
                    "quoted_price_cents",
                    None
                )
                or 0
            ),

            "notes": getattr(
                booking,
                "notes",
                None
            ),

            "source": getattr(
                booking,
                "source",
                None
            ),
        })


    # -----------------------------------------------------
    # DOCUMENTI
    # -----------------------------------------------------

    report_count = 0

    for document in documents:

        category = (
            document.category
            or "document"
        ).lower()

        if category == "report":
            report_count += 1

        timeline.append({
            "type": "document",
            "kind": (
                "report"
                if category == "report"
                else "document"
            ),

            "label": (
                "Referto"
                if category == "report"
                else "Documento"
            ),

            "date": (
                document.created_at.isoformat()
                if document.created_at
                else None
            ),

            "id": document.id,

            "booking_id": getattr(
                document,
                "booking_id",
                None
            ),

            "title": document.title,

            "category": category,

            "status": (
                document.status
                or "available"
            ),

            "filename": document.filename,
        })


    # -----------------------------------------------------
    # PAGAMENTI
    # -----------------------------------------------------

    paid_count = 0

    for payment in payments:

        status = (
            payment.status
            or "pending"
        ).lower()

        if status == "paid":
            paid_count += 1

        event_date = (
            getattr(payment, "paid_at", None)
            or getattr(payment, "created_at", None)
        )

        timeline.append({
            "type": "payment",
            "kind": "payment",

            "label": "Pagamento",

            "date": (
                event_date.isoformat()
                if event_date
                else None
            ),

            "id": payment.id,

            "title": (
                getattr(
                    payment,
                    "description",
                    None
                )
                or "Pagamento prestazione"
            ),

            "status": status,

            "amount_cents": (
                getattr(
                    payment,
                    "amount_cents",
                    None
                )
                or 0
            ),

            "currency": (
                getattr(
                    payment,
                    "currency",
                    None
                )
                or "EUR"
            ),

            "provider": getattr(
                payment,
                "provider",
                None
            ),

            "booking_id": getattr(
                payment,
                "booking_id",
                None
            ),
        })


    # -----------------------------------------------------
    # ORDINAMENTO TIMELINE
    # -----------------------------------------------------

    timeline.sort(
        key=lambda x: x.get("date") or "",
        reverse=True
    )

    timeline = timeline[:limit]

    user_row = patient.user

    return {
        "patient": {
            "id": patient.id,

            "full_name": (
                user_row.full_name
                if user_row
                else f"Paziente #{patient.id}"
            ),

            "email": (
                user_row.email
                if user_row
                else None
            ),

            "phone": (
                user_row.phone
                if user_row
                else None
            ),

            "fiscal_code": patient.fiscal_code,

            "date_of_birth": (
                patient.date_of_birth.isoformat()
                if patient.date_of_birth
                else None
            ),

            "identity_status": getattr(
                patient,
                "identity_status",
                None
            ),
        },

        "summary": {
            "bookings": len(bookings),
            "completed": completed_count,
            "future": future_count,
            "cancelled": cancelled_count,

            "documents": len(documents),
            "reports": report_count,

            "payments": len(payments),
            "paid": paid_count,

            "events": len(timeline),
        },

        "timeline": timeline,

        "bookings": [
            item
            for item in timeline
            if item["type"] == "booking"
        ],

        "documents": [
            item
            for item in timeline
            if item["type"] == "document"
        ],

        "payments": [
            item
            for item in timeline
            if item["type"] == "payment"
        ],
    }



# CUP_BOOKING_PATIENT_SEARCH_V1
@router.get("/search")
def search_patients(
    q: str = "",
    limit: int = 20,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    from sqlalchemy import or_

    term = (q or "").strip()

    if len(term) < 2:
        return []

    pattern = f"%{term}%"

    rows = (
        db.query(Patient)
        .join(User, User.id == Patient.user_id)
        .options(joinedload(Patient.user))
        .filter(
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                User.phone.ilike(pattern),
                Patient.fiscal_code.ilike(pattern),
            )
        )
        .order_by(User.full_name.asc())
        .limit(min(max(limit, 1), 50))
        .all()
    )

    return [patient_out(row) for row in rows]


@router.get("/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    patient = db.query(Patient).options(joinedload(Patient.user)).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paziente non trovato")
    return patient_out(patient)



@router.patch("/{patient_id}")
def update_patient(
    patient_id: int,
    payload: PatientUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator"))
):
    patient = (
        db.query(Patient)
        .options(joinedload(Patient.user))
        .filter(Patient.id == patient_id)
        .first()
    )

    if not patient:
        raise HTTPException(404, "Paziente non trovato")

    data = payload.model_dump(exclude_unset=True)

    user_row = patient.user

    if not user_row:
        raise HTTPException(
            409,
            "Paziente senza anagrafica utente associata"
        )

    # Nome e cognome strutturati.
    # full_name resta sincronizzato per compatibilita' con i moduli legacy.
    if "first_name" in data or "last_name" in data:
        first_name = (
            data.get("first_name")
            if "first_name" in data
            else user_row.first_name
        )
        last_name = (
            data.get("last_name")
            if "last_name" in data
            else user_row.last_name
        )

        first_name = (first_name or "").strip()
        last_name = (last_name or "").strip()

        if not first_name:
            raise HTTPException(422, "Nome obbligatorio")

        if not last_name:
            raise HTTPException(422, "Cognome obbligatorio")

        user_row.first_name = first_name
        user_row.last_name = last_name
        user_row.full_name = f"{first_name} {last_name}".strip()

    elif "full_name" in data:
        # Compatibilita' con eventuali client legacy.
        value = (data["full_name"] or "").strip()

        if not value:
            raise HTTPException(422, "Nome e cognome obbligatori")

        user_row.full_name = value

    if "email" in data:
        value = (data["email"] or "").strip().lower()

        if value:
            existing = (
                db.query(User)
                .filter(
                    User.email == value,
                    User.id != user_row.id
                )
                .first()
            )

            if existing:
                raise HTTPException(
                    409,
                    "Email gia associata a un altro utente"
                )

            user_row.email = value

    if "phone" in data:
        user_row.phone = (data["phone"] or "").strip() or None

    if "fiscal_code" in data:
        value = (data["fiscal_code"] or "").strip().upper()

        if value:
            existing = (
                db.query(Patient)
                .filter(
                    func.upper(func.trim(Patient.fiscal_code)) == value,
                    Patient.id != patient.id
                )
                .first()
            )

            if existing:
                raise HTTPException(
                    409,
                    "Codice fiscale gia associato a un altro paziente"
                )

        patient.fiscal_code = value or None

    if "notes" in data:
        patient.notes = (data["notes"] or "").strip() or None

    if "date_of_birth" in data:
        raw = (data["date_of_birth"] or "").strip()

        if raw:
            from datetime import date
            try:
                patient.date_of_birth = date.fromisoformat(raw)
            except ValueError:
                raise HTTPException(
                    422,
                    "Data di nascita non valida"
                )
        else:
            patient.date_of_birth = None

    if "reminder_enabled" in data:
        patient.reminder_enabled = (
            "true"
            if data["reminder_enabled"]
            else "false"
        )

    if "reminder_channels" in data:
        patient.reminder_channels = (
            (data["reminder_channels"] or "").strip()
            or None
        )

    db.commit()
    db.refresh(patient)
    db.refresh(patient, attribute_names=["user"])

    return patient_out(patient)


@router.patch("/{patient_id}/reminders")
def update_reminder_preferences(patient_id: int, payload: ReminderPreferences, db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Paziente non trovato")
    fields = payload.model_fields_set

    if "enabled" in fields:
        patient.reminder_enabled = (
            "true" if payload.enabled else "false"
        )

    if "channels" in fields:
        requested = [
            x.strip().lower()
            for x in str(payload.channels or "").split(",")
            if x.strip()
        ]

        # Telegram può essere abilitato solo se il paziente
        # è realmente collegato al bot.
        if (
            "telegram" in requested
            and not patient.reminder_telegram_chat_id
        ):
            raise HTTPException(
                422,
                "Telegram non disponibile: il paziente non ha collegato il bot"
            )

        patient.reminder_channels = (
            ",".join(dict.fromkeys(requested))
            or None
        )

    if "telegram_chat_id" in fields:
        patient.reminder_telegram_chat_id = (
            str(payload.telegram_chat_id).strip()
            if payload.telegram_chat_id
            else None
        )

        # Se viene scollegato Telegram, lo rimuoviamo anche
        # dai canali di reminder.
        if not patient.reminder_telegram_chat_id:
            channels = [
                x.strip().lower()
                for x in str(
                    patient.reminder_channels or ""
                ).split(",")
                if x.strip()
                and x.strip().lower() != "telegram"
            ]

            patient.reminder_channels = (
                ",".join(channels)
                or None
            )

    db.commit(); db.refresh(patient)
    db.refresh(patient, attribute_names=["user"])
    return patient_out(patient)


# ============================================================
# OMNIA_PATIENT_360_V1
# ============================================================

@router.get("/{patient_id}/overview")
def patient_overview(
    patient_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    """
    Vista operatore aggregata del paziente:
    anagrafica, prenotazioni, conversazioni e documenti.

    Logica delegata a app.services.patient_context_service
    (consolidata con l'endpoint /api/omnichannel/patients/{id}/operator-context
    nella Fase 1 di unificazione Patient Context, fix/patient-context-unify).
    """

    from app.services.patient_context_service import get_operator_full_overview

    overview = get_operator_full_overview(db, patient_id)

    if overview is None:
        raise HTTPException(
            status_code=404,
            detail="Paziente non trovato"
        )

    return overview


# /OMNIA_PATIENT_360_V1
