from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db.database import get_db
from app.models.patient import Patient
from app.models.patient_relationship import PatientRelationship

router = APIRouter(
    prefix="/api/patients",
    tags=["patient-relationships"],
)


class RelationshipCreate(BaseModel):
    relationship_type: str = "other"
    display_name: str
    phone: str | None = None
    email: str | None = None

    can_book: bool = False
    can_manage_bookings: bool = False
    can_receive_reminders: bool = False
    can_receive_document_requests: bool = False
    can_send_documents: bool = False

    authorization_type: str = "informal"
    authorization_notes: str | None = None
    is_primary: bool = False


def relationship_out(row: PatientRelationship):
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "related_user_id": row.related_user_id,
        "relationship_type": row.relationship_type,
        "display_name": row.display_name,
        "phone": row.phone,
        "email": row.email,
        "can_book": row.can_book,
        "can_manage_bookings": row.can_manage_bookings,
        "can_receive_reminders": row.can_receive_reminders,
        "can_receive_document_requests": row.can_receive_document_requests,
        "can_send_documents": row.can_send_documents,
        "authorization_type": row.authorization_type,
        "authorization_verified_at": row.authorization_verified_at,
        "authorization_notes": row.authorization_notes,
        "is_primary": row.is_primary,
        "is_active": row.is_active,
    }


@router.get("/{patient_id}/relationships")
def list_relationships(
    patient_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    if not db.get(Patient, patient_id):
        raise HTTPException(404, "Paziente non trovato")

    rows = (
        db.query(PatientRelationship)
        .filter(
            PatientRelationship.patient_id == patient_id,
            PatientRelationship.is_active.is_(True),
        )
        .order_by(
            PatientRelationship.is_primary.desc(),
            PatientRelationship.id.asc(),
        )
        .all()
    )

    return [relationship_out(row) for row in rows]


@router.post("/{patient_id}/relationships")
def create_relationship(
    patient_id: int,
    payload: RelationshipCreate,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    if not db.get(Patient, patient_id):
        raise HTTPException(404, "Paziente non trovato")

    row = PatientRelationship(
        patient_id=patient_id,
        relationship_type=payload.relationship_type,
        display_name=payload.display_name.strip(),
        phone=(payload.phone or "").strip() or None,
        email=(payload.email or "").strip() or None,
        can_book=payload.can_book,
        can_manage_bookings=payload.can_manage_bookings,
        can_receive_reminders=payload.can_receive_reminders,
        can_receive_document_requests=payload.can_receive_document_requests,
        can_send_documents=payload.can_send_documents,
        authorization_type=payload.authorization_type,
        authorization_notes=payload.authorization_notes,
        is_primary=payload.is_primary,
        is_active=True,
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return relationship_out(row)

class RelationshipUpdate(BaseModel):
    relationship_type: str | None = None
    display_name: str | None = None
    phone: str | None = None
    email: str | None = None
    can_book: bool | None = None
    can_manage_bookings: bool | None = None
    can_receive_reminders: bool | None = None
    can_receive_document_requests: bool | None = None
    can_send_documents: bool | None = None
    authorization_type: str | None = None
    authorization_notes: str | None = None
    is_primary: bool | None = None
    is_active: bool | None = None


@router.patch("/{patient_id}/relationships/{relationship_id}")
def update_relationship(
    patient_id: int,
    relationship_id: int,
    payload: RelationshipUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_role("admin", "operator")),
):
    row = (
        db.query(PatientRelationship)
        .filter(
            PatientRelationship.id == relationship_id,
            PatientRelationship.patient_id == patient_id,
        )
        .first()
    )

    if not row:
        raise HTTPException(404, "Contatto/delegato non trovato")

    values = payload.model_dump(exclude_unset=True)

    for key, value in values.items():
        if key in {"display_name", "phone", "email"} and value is not None:
            value = value.strip() or None
        setattr(row, key, value)

    db.commit()
    db.refresh(row)

    return relationship_out(row)
