from datetime import datetime, date, time

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.auth import (
    get_current_user,
    require_role,
)
from app.db.database import get_db

from app.models.booking import Booking
from app.models.patient import Patient
from app.models.calendar import Agenda, AgendaException
from app.models.reallocation import (
    ServiceInterruption,
    ServiceInterruptionAgenda,
    ReallocationCase,
)

from app.services.reallocation_service import (
    ensure_agenda_blocks,
    create_cases,
    notify_case,
    find_first_proposal,
    apply_reallocation,
    apply_cancellation,
)


router = APIRouter(
    prefix="/api/reallocation",
    tags=["reallocation"],
)


class IncidentCreate(BaseModel):
    scope_type: str = "agenda"

    agenda_id: int | None = None
    agenda_ids: list[int] = []

    specialty: str | None = None

    kind: str = "technical_fault"
    title: str
    note: str | None = None

    start_date: date
    end_date: date

    start_time: time | None = None
    end_time: time | None = None


class CaseProposal(BaseModel):
    proposed_agenda_id: int
    proposed_scheduled_at: datetime


class OperatorPhoneConfirm(BaseModel):
    note: str | None = None


def case_dict(row):
    booking = row.booking

    return {
        "id": row.id,
        "interruption_id": row.interruption_id,
        "booking_id": row.booking_id,
        "patient_name": (
            booking.patient.user.full_name
            if (
                booking
                and booking.patient
                and booking.patient.user
            )
            else None
        ),
        "service_name": (
            booking.service_name
            if booking else None
        ),
        "priority": (
            booking.priority
            if booking else None
        ),
        "status": row.status,
        "action": row.action,
        "original_agenda_id":
            row.original_agenda_id,
        "original_scheduled_at":
            row.original_scheduled_at,
        "proposed_agenda_id":
            row.proposed_agenda_id,
        "proposed_agenda_name": (
            row.proposed_agenda.name
            if row.proposed_agenda
            else None
        ),
        "proposed_scheduled_at":
            row.proposed_scheduled_at,
        "token_id": row.token_id,
        "notified_at": row.notified_at,
        "responded_at": row.responded_at,
        "note": row.note,
        "confirmation_source": row.confirmation_source,
        "confirmed_by": row.confirmed_by,
        "confirmed_at": row.confirmed_at,
        "confirmation_note": row.confirmation_note,
    }



def resolve_scope_agendas(
    db: Session,
    payload: IncidentCreate,
):
    scope = payload.scope_type

    q = (
        db.query(Agenda)
        .options(joinedload(Agenda.doctor))
        .filter(Agenda.active == True)
    )

    if scope == "agenda":

        if not payload.agenda_id:
            raise HTTPException(
                400,
                "Seleziona un'agenda"
            )

        rows = q.filter(
            Agenda.id == payload.agenda_id
        ).all()

    elif scope == "agendas":

        ids = list(
            dict.fromkeys(
                payload.agenda_ids or []
            )
        )

        if not ids:
            raise HTTPException(
                400,
                "Seleziona almeno un'agenda"
            )

        rows = q.filter(
            Agenda.id.in_(ids)
        ).all()

    elif scope == "specialty":

        specialty = (
            payload.specialty or ""
        ).strip()

        if not specialty:
            raise HTTPException(
                400,
                "Seleziona una specialità"
            )

        rows = [
            a
            for a in q.all()
            if (
                a.doctor
                and a.doctor.specialty
                == specialty
            )
        ]

    elif scope == "facility":

        rows = q.all()

    else:
        raise HTTPException(
            400,
            "Ambito non valido"
        )

    if not rows:
        raise HTTPException(
            400,
            "Nessuna agenda compatibile"
        )

    return rows


def incident_dict(row):
    return {
        "id": row.id,
        "agenda_id": row.agenda_id,
        "scope_type": row.scope_type or "agenda",
        "specialty": row.specialty,
        "facility_wide": bool(
            str(row.facility_wide).lower()
            in {"true","1","yes"}
        ),
        "agenda_name": (
            row.agenda.name
            if row.agenda else None
        ),
        "kind": row.kind,
        "title": row.title,
        "note": row.note,
        "start_date": row.start_date,
        "end_date": row.end_date,
        "start_time": row.start_time,
        "end_time": row.end_time,
        "status": row.status,
        "created_at": row.created_at,
    }


@router.post("/incidents")
def create_incident(
    payload: IncidentCreate,
    db: Session = Depends(get_db),
    user=Depends(
        require_role("admin", "operator")
    ),
):

    if payload.end_date < payload.start_date:
        raise HTTPException(
            400,
            "Intervallo date non valido",
        )

    agendas = resolve_scope_agendas(
        db,
        payload,
    )

    # Il vecchio agenda_id resta valorizzato
    # soltanto per il caso singola agenda.
    legacy_agenda_id = (
        agendas[0].id
        if payload.scope_type == "agenda"
        else None
    )

    row = ServiceInterruption(
        agenda_id=legacy_agenda_id,
        scope_type=payload.scope_type,
        specialty=(
            payload.specialty
            if payload.scope_type
            == "specialty"
            else None
        ),
        facility_wide=(
            "true"
            if payload.scope_type == "facility"
            else "false"
        ),
        kind=payload.kind,
        title=payload.title,
        note=payload.note,
        start_date=payload.start_date,
        end_date=payload.end_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        status="active",
        created_by=getattr(
            user,
            "id",
            None,
        ),
    )

    db.add(row)
    db.flush()

    for agenda in agendas:
        db.add(
            ServiceInterruptionAgenda(
                interruption_id=row.id,
                agenda_id=agenda.id,
            )
        )

    db.commit()
    db.refresh(row)

    ensure_agenda_blocks(
        db,
        row,
    )

    cases = create_cases(
        db,
        row,
        getattr(user, "id", None),
    )

    return {
        "incident": incident_dict(row),
        "agendas": [
            {
                "id": a.id,
                "name": a.name,
            }
            for a in agendas
        ],
        "agenda_count": len(agendas),
        "cases": len(cases),
        "proposals": sum(
            1
            for c in cases
            if c.status == "proposal_ready"
        ),
    }


@router.get("/incidents")
def list_incidents(
    db: Session = Depends(get_db),
    user=Depends(
        require_role("admin", "operator")
    ),
):
    rows = (
        db.query(ServiceInterruption)
        .options(
            joinedload(ServiceInterruption.agenda)
        )
        .order_by(
            ServiceInterruption.created_at.desc()
        )
        .limit(100)
        .all()
    )

    return [
        incident_dict(x)
        for x in rows
    ]



@router.delete("/incidents/{incident_id}")
def delete_incident(
    incident_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    incident = db.get(ServiceInterruption, incident_id)

    if not incident:
        raise HTTPException(
            404,
            "Interruzione non trovata"
        )

    cases = (
        db.query(ReallocationCase)
        .filter(
            ReallocationCase.interruption_id == incident_id
        )
        .all()
    )

    protected_statuses = {
        "notified",
        "accepted",
        "rejected",
        "contact_requested",
        "reallocated",
        "cancel_requested",
        "cancel_confirmed",
    }

    protected = [
        c for c in cases
        if c.status in protected_statuses
    ]

    if protected:
        raise HTTPException(
            409,
            "Impossibile eliminare: esistono pratiche "
            "gia notificate, riallocate o cancellate."
        )

    # Elimina solo i casi non ancora elaborati.
    for case in cases:
        db.delete(case)

    # Elimina esclusivamente i blocchi creati
    # da questa specifica interruzione.
    (
        db.query(AgendaException)
        .filter(
            AgendaException.note.like(
                f"Interruzione #{incident_id}%"
            )
        )
        .delete(synchronize_session=False)
    )

    db.delete(incident)
    db.commit()

    return {
        "ok": True,
        "incident_id": incident_id,
        "removed_cases": len(cases),
    }


@router.get("/incidents/{incident_id}")
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db),
    user=Depends(
        require_role("admin", "operator")
    ),
):
    row = (
        db.query(ServiceInterruption)
        .options(
            joinedload(ServiceInterruption.agenda)
        )
        .filter(
            ServiceInterruption.id == incident_id
        )
        .first()
    )

    if not row:
        raise HTTPException(
            404,
            "Interruzione non trovata",
        )

    cases = (
        db.query(ReallocationCase)
        .options(
            joinedload(ReallocationCase.booking)
            .joinedload(Booking.patient)
            .joinedload(Patient.user),
            joinedload(
                ReallocationCase.proposed_agenda
            ),
        )
        .filter(
            ReallocationCase.interruption_id ==
                incident_id
        )
        .order_by(
            ReallocationCase.id
        )
        .all()
    )

    cases.sort(
        key=lambda c: (
            0
            if (
                c.booking
                and c.booking.priority == "urgent"
            )
            else 1,
            c.original_scheduled_at,
        )
    )

    return {
        "incident": incident_dict(row),
        "cases": [
            case_dict(x)
            for x in cases
        ],
    }



@router.get("/cases/{case_id}/preview-message")
def preview_message(
    case_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    case = (
        db.query(ReallocationCase)
        .options(
            joinedload(ReallocationCase.booking),
            joinedload(ReallocationCase.proposed_agenda),
        )
        .filter(ReallocationCase.id == case_id)
        .first()
    )

    if not case or not case.booking:
        raise HTTPException(404, "Pratica non trovata")

    booking = case.booking

    if case.action == "cancel":
        text = (
            f"Il suo appuntamento {booking.service_name} del "
            f"{booking.scheduled_at.strftime('%d/%m/%Y')} "
            f"alle {booking.scheduled_at.strftime('%H:%M')} "
            "deve essere annullato per indisponibilità del servizio."
        )
    else:
        if not case.proposed_scheduled_at:
            raise HTTPException(400, "Nessuna proposta disponibile")

        text = (
            "Per indisponibilità del servizio dobbiamo riprogrammare "
            f"il suo appuntamento {booking.service_name} del "
            f"{booking.scheduled_at.strftime('%d/%m/%Y')} "
            f"alle {booking.scheduled_at.strftime('%H:%M')}. "
            "Nuova proposta: "
            f"{case.proposed_scheduled_at.strftime('%d/%m/%Y')} "
            f"ore {case.proposed_scheduled_at.strftime('%H:%M')}."
        )

    return {
        "case_id": case.id,
        "patient_name": (
            booking.patient.user.full_name
            if booking.patient and booking.patient.user
            else None
        ),
        "message": text,
        "actions": [
            "accept",
            "reject",
            "contact",
        ]
    }



@router.post("/cases/{case_id}/simulate-notify")
def simulate_proposal(
    case_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    """
    Modalita demo:
    registra la proposta come notificata ma NON invia
    SMS, WhatsApp, email o altri messaggi esterni.
    """
    from uuid import uuid4

    case = (
        db.query(ReallocationCase)
        .options(
            joinedload(ReallocationCase.booking),
            joinedload(ReallocationCase.proposed_agenda),
        )
        .filter(ReallocationCase.id == case_id)
        .first()
    )

    if not case:
        raise HTTPException(404, "Pratica non trovata")

    if case.status in {
        "reallocated",
        "cancel_confirmed",
    }:
        raise HTTPException(409, "Pratica gia completata")

    if (
        case.action != "cancel"
        and not case.proposed_scheduled_at
    ):
        raise HTTPException(
            400,
            "Nessuna proposta disponibile"
        )

    if not case.token_id:
        case.token_id = uuid4().hex

    case.status = (
        "cancel_requested"
        if case.action == "cancel"
        else "notified"
    )

    case.notified_at = datetime.now()

    note = case.note or ""
    marker_text = "[SIMULAZIONE INVIO]"

    if marker_text not in note:
        case.note = (
            (note + "\n" if note else "")
            + marker_text
        )

    db.commit()
    db.refresh(case)

    return {
        "ok": True,
        "simulation": True,
        "case_id": case.id,
        "status": case.status,
        "token_id": case.token_id,
        "notified_at": case.notified_at,
        "provider_called": False,
    }


@router.post("/cases/{case_id}/notify")
def send_proposal(
    case_id: int,
    db: Session = Depends(get_db),
    user=Depends(
        require_role("admin", "operator")
    ),
):
    case = (
        db.query(ReallocationCase)
        .options(
            joinedload(ReallocationCase.booking)
        )
        .filter(
            ReallocationCase.id == case_id
        )
        .first()
    )

    if not case:
        raise HTTPException(
            404,
            "Pratica non trovata",
        )

    try:
        results = notify_case(
            db,
            case,
        )
    except ValueError as exc:
        raise HTTPException(
            400,
            str(exc),
        )

    return {
        "ok": True,
        "case": case_dict(case),
        "delivery": results,
    }


@router.post("/cases/{case_id}/cancel-request")
def cancel_request(
    case_id: int,
    db: Session = Depends(get_db),
    user=Depends(
        require_role("admin", "operator")
    ),
):
    case = db.get(
        ReallocationCase,
        case_id,
    )

    if not case:
        raise HTTPException(
            404,
            "Pratica non trovata",
        )

    case.action = "cancel"
    case.operator_id = getattr(
        user,
        "id",
        None,
    )

    db.commit()

    try:
        results = notify_case(
            db,
            case,
        )
    except ValueError as exc:
        raise HTTPException(
            400,
            str(exc),
        )

    return {
        "ok": True,
        "delivery": results,
    }



@router.post("/cases/{case_id}/operator-phone-confirm")
def operator_phone_confirm(
    case_id: int,
    payload: OperatorPhoneConfirm,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    case = db.get(ReallocationCase, case_id)

    if not case:
        raise HTTPException(404, "Pratica non trovata")

    if case.status in {
        "reallocated",
        "cancel_confirmed"
    }:
        raise HTTPException(409, "Pratica già completata")

    try:
        if case.action == "cancel":
            apply_cancellation(
                db,
                case,
                getattr(user, "id", None),
            )
        else:
            if not case.proposed_scheduled_at:
                raise HTTPException(
                    400,
                    "Nessuna nuova data proposta"
                )

            apply_reallocation(
                db,
                case,
                getattr(user, "id", None),
            )

        case.confirmation_source = "operator_phone"
        case.confirmed_by = getattr(user, "id", None)
        case.confirmed_at = datetime.now()
        case.confirmation_note = (
            payload.note
            or "Confermato telefonicamente con il paziente"
        )

        db.commit()
        db.refresh(case)

        return {
            "ok": True,
            "status": case.status,
            "confirmation_source": case.confirmation_source,
            "confirmed_at": case.confirmed_at,
        }

    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/cases/{case_id}/operator-accept")
def operator_accept(
    case_id: int,
    db: Session = Depends(get_db),
    user=Depends(
        require_role("admin", "operator")
    ),
):
    case = db.get(
        ReallocationCase,
        case_id,
    )

    if not case:
        raise HTTPException(
            404,
            "Pratica non trovata",
        )

    try:
        if case.action == "cancel":
            apply_cancellation(
                db,
                case,
                getattr(user, "id", None),
            )
        else:
            apply_reallocation(
                db,
                case,
                getattr(user, "id", None),
            )
    except ValueError as exc:
        raise HTTPException(
            400,
            str(exc),
        )

    return {"ok": True}


@router.get("/public/{token}")
def public_case(
    token: str,
    db: Session = Depends(get_db),
):
    case = (
        db.query(ReallocationCase)
        .options(
            joinedload(ReallocationCase.booking),
            joinedload(
                ReallocationCase.proposed_agenda
            ),
        )
        .filter(
            ReallocationCase.token_id == token
        )
        .first()
    )

    if not case:
        raise HTTPException(
            404,
            "Richiesta non valida",
        )

    return case_dict(case)


@router.post("/public/{token}/{action}")
def public_response(
    token: str,
    action: str,
    db: Session = Depends(get_db),
):
    case = (
        db.query(ReallocationCase)
        .filter(
            ReallocationCase.token_id == token
        )
        .with_for_update()
        .first()
    )

    if not case:
        raise HTTPException(
            404,
            "Richiesta non valida",
        )

    if action not in {
        "accept",
        "reject",
        "contact",
    }:
        raise HTTPException(
            400,
            "Risposta non valida",
        )

    if case.status in {
        "reallocated",
        "cancel_confirmed",
    }:
        raise HTTPException(
            409,
            "Richiesta già completata",
        )

    now = datetime.now()
    case.responded_at = now

    # ---------------------------------------------
    # PAZIENTE RIFIUTA LA PROPOSTA
    # ---------------------------------------------

    if action == "reject":

        case.status = "rejected"
        case.confirmation_source = "patient"
        case.confirmed_at = None

        db.commit()

        return {
            "ok": True,
            "status": "rejected",
        }

    # ---------------------------------------------
    # PAZIENTE RICHIEDE CONTATTO
    # ---------------------------------------------

    if action == "contact":

        case.status = "contact_requested"

        db.commit()

        return {
            "ok": True,
            "status": "contact_requested",
        }

    # ---------------------------------------------
    # PAZIENTE ACCETTA
    # ---------------------------------------------

    if case.action == "cancel":

        try:
            apply_cancellation(
                db,
                case,
            )
        except ValueError as exc:
            raise HTTPException(
                409,
                str(exc),
            )

        case.confirmation_source = "patient"
        case.confirmed_at = now
        case.confirmation_note = (
            "Cancellazione confermata dal paziente"
        )

        db.commit()

        return {
            "ok": True,
            "status": "cancel_confirmed",
        }

    if not case.proposed_scheduled_at:
        raise HTTPException(
            409,
            "Nuova data non disponibile",
        )

    try:
        apply_reallocation(
            db,
            case,
        )
    except ValueError as exc:
        raise HTTPException(
            409,
            str(exc),
        )

    case.confirmation_source = "patient"
    case.confirmed_at = now
    case.confirmation_note = (
        "Nuova data accettata dal paziente"
    )

    db.commit()

    return {
        "ok": True,
        "status": "reallocated",
        "scheduled_at": case.proposed_scheduled_at,
    }


# CUP_REALLOCATED_BOOKING_FLAGS_V1

@router.get("/reallocated-bookings")
def reallocated_bookings(
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    rows = (
        db.query(ReallocationCase)
        .filter(
            ReallocationCase.status == "reallocated"
        )
        .order_by(
            ReallocationCase.completed_at.desc()
        )
        .all()
    )

    result = []

    for row in rows:

        source = (
            row.confirmation_source
            or "unknown"
        )

        labels = {
            "patient":
                "Accettata dal paziente",

            "operator_phone":
                "Confermata telefonicamente",

            "operator_desk":
                "Confermata allo sportello",

            "unknown":
                "Riallocazione confermata",
        }

        result.append({
            "booking_id": row.booking_id,
            "case_id": row.id,
            "confirmation_source": source,
            "confirmation_label":
                labels.get(
                    source,
                    "Riallocazione confermata"
                ),
            "original_scheduled_at":
                row.original_scheduled_at,
            "confirmed_at":
                row.confirmed_at
                or row.completed_at,
            "confirmation_note":
                row.confirmation_note,
        })

    return result

# /CUP_REALLOCATED_BOOKING_FLAGS_V1
