from __future__ import annotations

from datetime import datetime, date, time, timedelta
from uuid import uuid4

from sqlalchemy.orm import joinedload

from app.config import settings
from app.models.booking import Booking
from app.models.patient import Patient
from app.models.calendar import (
    Agenda,
    AgendaException,
    Doctor,
)
from app.models.reallocation import (
    ServiceInterruption,
    ServiceInterruptionAgenda,
    ReallocationCase,
)
from app.services.customer_delivery import send_patient_message


def now():
    return datetime.now()




def interruption_agenda_ids(db, interruption):
    """
    Restituisce lo snapshot concreto delle agende
    interessate dall'interruzione.
    """
    ids = [
        row.agenda_id
        for row in (
            db.query(ServiceInterruptionAgenda)
            .filter(
                ServiceInterruptionAgenda.interruption_id
                == interruption.id
            )
            .all()
        )
    ]

    # Compatibilità vecchie interruzioni.
    if not ids and interruption.agenda_id:
        ids = [interruption.agenda_id]

    return list(dict.fromkeys(ids))


def affected_bookings(db, interruption):
    start = datetime.combine(
        interruption.start_date,
        interruption.start_time or time.min,
    )

    end = datetime.combine(
        interruption.end_date,
        interruption.end_time or time.max,
    )

    agenda_ids = interruption_agenda_ids(
        db,
        interruption,
    )

    if not agenda_ids:
        return []

    return (
        db.query(Booking)
        .options(
            joinedload(Booking.patient)
            .joinedload(Patient.user),
            joinedload(Booking.agenda)
            .joinedload(Agenda.doctor),
            joinedload(Booking.visit_type),
            joinedload(Booking.doctors),
        )
        .filter(
            Booking.agenda_id.in_(agenda_ids),
            Booking.status.notin_(
                ["cancelled", "completed"]
            ),
            Booking.scheduled_at < end,
            Booking.end_at > start,
        )
        .order_by(
            Booking.priority.desc(),
            Booking.scheduled_at.asc(),
        )
        .all()
    )

def ensure_agenda_blocks(db, interruption):

    agenda_ids = interruption_agenda_ids(
        db,
        interruption,
    )

    for agenda_id in agenda_ids:

        current = interruption.start_date

        while current <= interruption.end_date:

            marker = (
                f"Interruzione #{interruption.id}"
            )

            existing = (
                db.query(AgendaException)
                .filter(
                    AgendaException.agenda_id
                    == agenda_id,
                    AgendaException.date
                    == current,
                    AgendaException.kind
                    == "blocked",
                    AgendaException.note.like(
                        marker + "%"
                    ),
                )
                .first()
            )

            if not existing:
                db.add(
                    AgendaException(
                        agenda_id=agenda_id,
                        date=current,
                        start_time=
                            interruption.start_time,
                        end_time=
                            interruption.end_time,
                        kind="blocked",
                        note=(
                            marker
                            + " | "
                            + interruption.title
                        ),
                    )
                )

            current += timedelta(days=1)

    db.commit()

def candidate_agendas(db, booking):
    source = (
        db.query(Agenda)
        .options(
            joinedload(Agenda.doctor),
            joinedload(Agenda.visit_types),
        )
        .filter(Agenda.id == booking.agenda_id)
        .first()
    )

    if not source:
        return []

    all_agendas = (
        db.query(Agenda)
        .options(
            joinedload(Agenda.doctor),
            joinedload(Agenda.visit_types),
            joinedload(Agenda.rules),
        )
        .filter(Agenda.active == True)
        .all()
    )

    visit_id = booking.visit_type_id
    source_doctor = source.doctor
    specialty = source_doctor.specialty if source_doctor else None

    compatible = [
        a for a in all_agendas
        if (
            not visit_id
            or visit_id in {v.id for v in a.visit_types}
        )
    ]

    same_agenda = [
        a for a in compatible
        if a.id == source.id
    ]

    same_doctor = [
        a for a in compatible
        if (
            a.id != source.id
            and a.doctor_id == source.doctor_id
        )
    ]

    same_specialty = [
        a for a in compatible
        if (
            a.doctor_id != source.doctor_id
            and specialty
            and a.doctor
            and a.doctor.specialty == specialty
        )
    ]

    seen = set()
    ordered = []

    for group in (
        same_agenda,
        same_doctor,
        same_specialty,
    ):
        for agenda in group:
            if agenda.id not in seen:
                seen.add(agenda.id)
                ordered.append(agenda)

    return ordered


def _rules_for_day(agenda, day):
    return [
        r for r in agenda.rules
        if (
            r.active
            and r.weekday == day.weekday()
            and (not r.valid_from or r.valid_from <= day)
            and (not r.valid_to or r.valid_to >= day)
        )
    ]


def _slot_free(
    db,
    agenda,
    visit,
    day,
    start_dt,
    end_dt,
    booking_id,
    reserved,
):
    if (agenda.id, start_dt) in reserved:
        return False

    blocked = (
        db.query(AgendaException)
        .filter(
            AgendaException.agenda_id == agenda.id,
            AgendaException.date == day,
            AgendaException.kind == "blocked",
        )
        .all()
    )

    for ex in blocked:
        ex_start = (
            datetime.combine(day, ex.start_time)
            if ex.start_time else
            datetime.combine(day, time.min)
        )

        ex_end = (
            datetime.combine(day, ex.end_time)
            if ex.end_time else
            datetime.combine(day, time.max)
        )

        if ex_start < end_dt and ex_end > start_dt:
            return False

    conflict = (
        db.query(Booking)
        .filter(
            Booking.id != booking_id,
            Booking.agenda_id == agenda.id,
            Booking.status != "cancelled",
            Booking.scheduled_at < end_dt,
            Booking.end_at > start_dt,
        )
        .first()
    )

    if conflict:
        return False

    return True


def find_first_proposal(
    db,
    booking,
    reserved=None,
    days=45,
):
    reserved = reserved or set()

    visit = booking.visit_type

    duration = (
        visit.duration_minutes
        if visit
        else (
            int(
                (
                    booking.end_at -
                    booking.scheduled_at
                ).total_seconds() / 60
            )
            if booking.end_at
            else 30
        )
    )

    today = date.today()

    start_date = max(
        today,
        booking.scheduled_at.date(),
    )

    current_time = now()

    for agenda in candidate_agendas(db, booking):

        for offset in range(days):

            day = start_date + timedelta(days=offset)

            for rule in _rules_for_day(agenda, day):

                cur = datetime.combine(
                    day,
                    rule.start_time,
                )

                limit = datetime.combine(
                    day,
                    rule.end_time,
                )

                while (
                    cur + timedelta(minutes=duration)
                    <= limit
                ):
                    finish = (
                        cur + timedelta(minutes=duration)
                    )

                    if cur > current_time:
                        if _slot_free(
                            db,
                            agenda,
                            visit,
                            day,
                            cur,
                            finish,
                            booking.id,
                            reserved,
                        ):
                            return {
                                "agenda": agenda,
                                "start": cur,
                                "end": finish,
                            }

                    cur += timedelta(
                        minutes=agenda.slot_minutes
                    )

    return None


def create_cases(db, interruption, operator_id=None):
    bookings = affected_bookings(
        db,
        interruption,
    )

    reserved = set()
    result = []

    for booking in bookings:

        existing = (
            db.query(ReallocationCase)
            .filter(
                ReallocationCase.interruption_id ==
                    interruption.id,
                ReallocationCase.booking_id ==
                    booking.id,
            )
            .first()
        )

        if existing:
            result.append(existing)
            continue

        case = ReallocationCase(
            interruption_id=interruption.id,
            booking_id=booking.id,
            original_agenda_id=booking.agenda_id,
            original_scheduled_at=booking.scheduled_at,
            original_end_at=booking.end_at,
            operator_id=operator_id,
            status="pending",
            action="reallocate",
        )

        proposal = find_first_proposal(
            db,
            booking,
            reserved,
        )

        if proposal:
            case.proposed_agenda_id = (
                proposal["agenda"].id
            )
            case.proposed_scheduled_at = (
                proposal["start"]
            )
            case.proposed_end_at = (
                proposal["end"]
            )
            case.status = "proposal_ready"

            reserved.add(
                (
                    proposal["agenda"].id,
                    proposal["start"],
                )
            )

        db.add(case)
        result.append(case)

    db.commit()

    return result


def patient_url(case):
    base = settings.CUP_PUBLIC_BASE_URL.rstrip("/")
    path = (
        "/reallocation.html?token="
        + case.token_id
    )

    return base + path if base else path


def notify_case(db, case):
    booking = (
        db.query(Booking)
        .options(
            joinedload(Booking.patient)
            .joinedload(Patient.user),
            joinedload(Booking.visit_type),
        )
        .filter(Booking.id == case.booking_id)
        .first()
    )

    if not booking or not booking.patient:
        raise ValueError("Paziente non disponibile")

    if not case.token_id:
        case.token_id = uuid4().hex

    if case.action == "cancel":
        text = (
            "Il suo appuntamento "
            f"{booking.service_name} del "
            f"{booking.scheduled_at.strftime('%d/%m/%Y')} "
            f"alle {booking.scheduled_at.strftime('%H:%M')} "
            "deve essere annullato per indisponibilita "
            "tecnica. Confermi la cancellazione oppure "
            f"richieda assistenza: {patient_url(case)}"
        )
    else:
        if not case.proposed_scheduled_at:
            raise ValueError(
                "Nessuna proposta di riallocazione"
            )

        text = (
            "Per indisponibilita tecnica dobbiamo "
            "riprogrammare il suo appuntamento "
            f"{booking.service_name} del "
            f"{booking.scheduled_at.strftime('%d/%m/%Y')} "
            f"alle {booking.scheduled_at.strftime('%H:%M')}. "
            "Nuova proposta: "
            f"{case.proposed_scheduled_at.strftime('%d/%m/%Y')} "
            f"ore {case.proposed_scheduled_at.strftime('%H:%M')}. "
            "Accetti, rifiuti o richieda un contatto: "
            f"{patient_url(case)}"
        )

    results = send_patient_message(
        booking.patient,
        text,
        booking.patient.reminder_channels,
        "sms,email",
        subject="Riprogrammazione appuntamento CUP",
    )

    case.status = (
        "cancel_requested"
        if case.action == "cancel"
        else "notified"
    )

    case.notified_at = now()

    db.commit()
    db.refresh(case)

    return results


def apply_reallocation(db, case, operator_id=None):
    booking = (
        db.query(Booking)
        .options(
            joinedload(Booking.doctors),
            joinedload(Booking.visit_type),
        )
        .filter(Booking.id == case.booking_id)
        .first()
    )

    agenda = db.get(
        Agenda,
        case.proposed_agenda_id,
    )

    if not booking or not agenda:
        raise ValueError(
            "Prenotazione o agenda non disponibile"
        )

    booking.agenda_id = agenda.id
    booking.scheduled_at = case.proposed_scheduled_at
    booking.end_at = case.proposed_end_at
    booking.doctors = [agenda.doctor]
    booking.status = "confirmed"

    case.status = "reallocated"
    case.completed_at = now()

    if operator_id:
        case.operator_id = operator_id

    db.commit()

    return booking


def apply_cancellation(db, case, operator_id=None):
    booking = db.get(
        Booking,
        case.booking_id,
    )

    if not booking:
        raise ValueError(
            "Prenotazione non trovata"
        )

    booking.status = "cancelled"

    case.status = "cancel_confirmed"
    case.completed_at = now()

    if operator_id:
        case.operator_id = operator_id

    db.commit()

    return booking
