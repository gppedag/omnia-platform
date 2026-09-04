"""
Patient Context Read Layer — v1.1.2


Servizio di sola lettura per l'aggregazione dei dati contesto paziente.

Riduce la duplicazione tra:
  - GET /api/patients/{patient_id}/overview   (patient_routes.py)
  - GET /api/omnichannel/patients/{patient_id}/operator-context (omnichannel_routes.py)

Entrambi endpoint query di bookings + documents.
- overview usa ORM + shape propria
- operator-context usa raw SQL + shape diversa

Il servizio centralizza la logica ORM di lettura.
operator-context mantiene il suo percorso raw SQL per compatibilità.

La funzione load_patient_context() restituisce ORM objects:
  - overview li usa direttamente
  - non interferisce con operator-context

count_pending_bookings() è una pura helper indipendente.

"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.portal import PatientDocument

logger = logging.getLogger("patient_context")


def load_bookings(
    db: Session,
    patient_id: int,
    limit: int = 50,
) -> list[Booking]:
    """
    Carica bookings per paziente (ORM).

    Ritorna list[Booking] — ORM objects.
    """
    try:
        return (
            db.query(Booking)
            .filter(Booking.patient_id == patient_id)
            .order_by(Booking.scheduled_at.desc())
            .limit(limit)
            .all()
        )
    except Exception:
        logger.exception(
            "patient_context: load_bookings failed patient_id=%s limit=%s",
            patient_id, limit,
        )
        return []


def load_documents(
    db: Session,
    patient_id: int,
    limit: int = 50,
) -> list[PatientDocument]:
    """
    Carica patient_documents per paziente (ORM).

    Ritorna list[PatientDocument] — ORM objects.
    """
    try:
        return (
            db.query(PatientDocument)
            .filter(PatientDocument.patient_id == patient_id)
            .order_by(PatientDocument.created_at.desc())
            .limit(limit)
            .all()
        )
    except Exception:
        logger.exception(
            "patient_context: load_documents failed patient_id=%s limit=%s",
            patient_id, limit,
        )
        return []


def load_patient_context(
    db: Session,
    patient_id: int,
    *,
    bookings_limit: int = 50,
    documents_limit: int = 50,
) -> dict[str, Any]:
    """
    Carica in una sola chiamata tutte le risorse di contesto paziente.

    Ritorna ORM objects per compatibilità con l'endpoint /overview.

    {
        "patient_id": int,
        "bookings": list[Booking],
        "documents": list[PatientDocument],
    }

    Ogni endpoint usa i propri ORM objects.
    """
    return {
        "patient_id": patient_id,
        "bookings": load_bookings(db, patient_id, bookings_limit),
        "documents": load_documents(db, patient_id, documents_limit),
    }


def count_pending_bookings(bookings: list[Booking]) -> int:
    """Conta prenotazioni con stato 'in corso' da una lista di ORM Booking objects."""
    pending_states = {"pending", "waiting", "requested", "hold", "held"}
    return sum(
        1 for b in bookings
        if str(getattr(b, "status", "") or "").lower() in pending_states
    )
