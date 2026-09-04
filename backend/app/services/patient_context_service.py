"""
Servizio unificato per il contesto paziente lato operatore.

Consolida due implementazioni precedenti che leggevano gli stessi dati
(prenotazioni, documenti, conversazioni) con query indipendenti e forme
di risposta divergenti:

- ``GET /api/patients/{id}/overview``            (patient_routes.py, ORM)
- ``GET /api/omnichannel/patients/{id}/operator-context`` (omnichannel_routes.py, SQL grezzo)

Questo modulo NON introduce un nuovo contratto pubblico: entrambe le route
restano invariate nel path e nella forma della risposta. Qui vive solo la
logica di lettura condivisa, cosi' i due endpoint diventano thin wrapper.

Nota di robustezza: la lettura di bookings/documenti resta difensiva
rispetto a tabelle mancanti o non ancora migrate (via ``sqlalchemy.inspect``),
comportamento gia' presente nella versione "operator-context" e necessario
per l'uso da Omnia Console in ambienti con schema non allineato.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session, joinedload

logger = logging.getLogger("cup_system.patient_context")

PENDING_BOOKING_STATUSES = {
    "pending",
    "waiting",
    "requested",
    "hold",
    "held",
}


def _table_names(db: Session) -> set[str]:
    return set(sa_inspect(db.bind).get_table_names())


def _fetch_bookings_raw(db: Session, patient_id: int, limit: int) -> list[dict[str, Any]]:
    """Lettura difensiva delle prenotazioni via SQL grezzo.

    Tollera l'assenza della tabella e colonne mancanti/alternative
    (service_name/service/visit_name), come nella implementazione
    "operator-context" originale.
    """
    tables = _table_names(db)
    if "bookings" not in tables:
        return []

    try:
        rows = (
            db.execute(
                sa_text(
                    """
                    SELECT *
                    FROM bookings
                    WHERE patient_id = :patient_id
                    ORDER BY scheduled_at DESC
                    LIMIT :limit
                    """
                ),
                {"patient_id": patient_id, "limit": limit},
            )
            .mappings()
            .all()
        )
    except Exception:
        logger.exception(
            "patient_context: lettura bookings fallita patient_id=%s",
            patient_id,
        )
        return []

    return [dict(row) for row in rows]


def _fetch_documents_raw(db: Session, patient_id: int, limit: int) -> list[dict[str, Any]]:
    """Lettura difensiva dei documenti via SQL grezzo (stessa logica di bookings)."""
    tables = _table_names(db)
    if "patient_documents" not in tables:
        return []

    try:
        rows = (
            db.execute(
                sa_text(
                    """
                    SELECT *
                    FROM patient_documents
                    WHERE patient_id = :patient_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"patient_id": patient_id, "limit": limit},
            )
            .mappings()
            .all()
        )
    except Exception:
        logger.exception(
            "patient_context: lettura patient_documents fallita patient_id=%s",
            patient_id,
        )
        return []

    return [dict(row) for row in rows]


def get_operator_light_context(
    db: Session,
    patient_id: int,
    *,
    bookings_limit: int = 8,
    documents_limit: int = 8,
) -> dict[str, Any]:
    """
    Contesto leggero per pannelli "durante l'interazione" (es. Omnia Console).

    Sostituisce 1:1 la logica precedentemente duplicata in
    ``omnichannel_routes.omnia_operator_patient_context``. Stessa forma di
    risposta, stessa tolleranza a tabelle/colonne mancanti.
    """
    raw_bookings = _fetch_bookings_raw(db, patient_id, bookings_limit)
    raw_documents = _fetch_documents_raw(db, patient_id, documents_limit)

    bookings: list[dict[str, Any]] = []
    pending_count = 0

    for data in raw_bookings:
        status = str(data.get("status") or "").lower()
        if status in PENDING_BOOKING_STATUSES:
            pending_count += 1

        bookings.append(
            {
                "id": data.get("id"),
                "service_name": (
                    data.get("service_name")
                    or data.get("service")
                    or data.get("visit_name")
                    or "Prestazione"
                ),
                "scheduled_at": data.get("scheduled_at"),
                "status": data.get("status"),
                "regime": (data.get("care_regime") or data.get("regime")),
                "price_cents": (
                    data.get("quoted_price_cents") or data.get("price_cents")
                ),
                "agenda_id": data.get("agenda_id"),
            }
        )

    documents: list[dict[str, Any]] = [
        {
            "id": data.get("id"),
            "title": (data.get("title") or data.get("filename") or "Documento"),
            "filename": data.get("filename"),
            "category": data.get("category"),
            "status": data.get("status"),
            "created_at": data.get("created_at"),
        }
        for data in raw_documents
    ]

    return {
        "ok": True,
        "patient_id": patient_id,
        "bookings": bookings,
        "documents": documents,
        "pending_count": pending_count,
    }


def get_operator_full_overview(
    db: Session,
    patient_id: int,
    *,
    bookings_limit: int = 50,
    sessions_limit: int = 20,
    messages_per_session: int = 30,
    documents_limit: int = 50,
) -> dict[str, Any] | None:
    """
    Vista operatore aggregata e completa del paziente: anagrafica,
    prenotazioni, conversazioni e documenti.

    Sostituisce 1:1 la logica precedentemente duplicata in
    ``patient_routes.patient_overview``. Ritorna ``None`` se il paziente
    non esiste (la route chiamante decide come tradurlo in HTTP 404).

    A differenza di ``get_operator_light_context`` usa l'ORM (non SQL
    grezzo) perche' e' il percorso storico gia' usato da app.js e include
    le conversazioni, assenti nella vista leggera.
    """
    from app.models.booking import Booking
    from app.models.chat import ChatSession
    from app.models.patient import Patient
    from app.models.portal import PatientDocument

    patient = (
        db.query(Patient)
        .options(joinedload(Patient.user))
        .filter(Patient.id == patient_id)
        .first()
    )

    if not patient:
        return None

    bookings = (
        db.query(Booking)
        .filter(Booking.patient_id == patient_id)
        .order_by(Booking.scheduled_at.desc())
        .limit(bookings_limit)
        .all()
    )

    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.patient_id == patient_id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        .limit(sessions_limit)
        .all()
    )

    documents = (
        db.query(PatientDocument)
        .filter(PatientDocument.patient_id == patient_id)
        .order_by(PatientDocument.created_at.desc())
        .limit(documents_limit)
        .all()
    )

    conversations = []
    for session in sessions:
        messages = list(session.messages or [])[-messages_per_session:]
        conversations.append(
            {
                "id": session.id,
                "channel": session.channel,
                "status": session.status,
                "sender_id": session.sender_id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "messages": [
                    {
                        "id": message.id,
                        "role": message.role,
                        "content": message.content,
                        "created_at": message.created_at,
                    }
                    for message in messages
                ],
            }
        )

    return {
        "patient": {
            "id": patient.id,
            "full_name": patient.user.full_name if patient.user else None,
            "phone": patient.user.phone if patient.user else None,
            "email": patient.user.email if patient.user else None,
            "fiscal_code": patient.fiscal_code,
            "date_of_birth": patient.date_of_birth,
            "notes": patient.notes,
        },
        "bookings": [
            {
                "id": booking.id,
                "service_name": booking.service_name,
                "scheduled_at": booking.scheduled_at,
                "end_at": booking.end_at,
                "status": booking.status,
                "priority": booking.priority,
                "notes": booking.notes,
                "care_regime": booking.care_regime,
                "source": booking.source,
            }
            for booking in bookings
        ],
        "conversations": conversations,
        "documents": [
            {
                "id": document.id,
                "booking_id": document.booking_id,
                "category": document.category,
                "title": document.title,
                "filename": document.filename,
                "mime_type": document.mime_type,
                "status": document.status,
                "created_at": document.created_at,
            }
            for document in documents
        ],
    }
