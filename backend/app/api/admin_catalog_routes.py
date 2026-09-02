from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db.database import get_db
from app.models.calendar import Doctor, VisitType

router = APIRouter(prefix="/api/admin/catalog", tags=["admin-catalog"])

def _has_column(model, name: str) -> bool:
    return name in model.__table__.columns.keys()

def _value(obj, name: str, default=None):
    return getattr(obj, name, default) if hasattr(obj, name) else default

def _doctor_payload(d: Doctor, visit_ids: list[int] | None = None) -> dict[str, Any]:
    return {
        "id": d.id,
        "full_name": _value(d, "full_name"),
        "specialty": _value(d, "specialty"),
        "email": _value(d, "email"),
        "color_hex": _value(d, "color_hex"),
        "active": _value(d, "active", True),
        "external_provider": _value(d, "external_provider", "none"),
        "visit_type_ids": visit_ids or [],
    }

def _visit_payload(v: VisitType) -> dict[str, Any]:
    return {
        "id": v.id,
        "code": _value(v, "code"),
        "name": _value(v, "name"),
        "duration_minutes": _value(v, "duration_minutes", 60),
        "color_hex": _value(v, "color_hex") or _value(v, "color"),
        "active": _value(v, "active", True),
        "private_price_cents": _value(v, "private_price_cents", 0),
        "ssn_enabled": _value(v, "ssn_enabled", False),
        "ssn_ticket_cents": _value(v, "ssn_ticket_cents", 0),
        "requires_prescription": _value(v, "requires_prescription", False),
    }

def _mapping(db: Session) -> dict[int, list[int]]:
    rows = db.execute(text(
        "SELECT doctor_id, visit_type_id FROM doctor_visit_types ORDER BY doctor_id, visit_type_id"
    )).all()
    result: dict[int, list[int]] = {}
    for doctor_id, visit_type_id in rows:
        result.setdefault(int(doctor_id), []).append(int(visit_type_id))
    return result

class DoctorIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    specialty: str | None = None
    email: str | None = None
    color_hex: str | None = None
    active: bool = True

class VisitTypeIn(BaseModel):
    code: str | None = None
    name: str = Field(min_length=2, max_length=200)
    duration_minutes: int = Field(default=60, ge=5, le=480)
    color_hex: str | None = None
    active: bool = True
    private_price_cents: int = Field(default=0, ge=0)
    ssn_enabled: bool = False
    ssn_ticket_cents: int = Field(default=0, ge=0)
    requires_prescription: bool = False

class DoctorVisitTypesIn(BaseModel):
    visit_type_ids: list[int] = []

@router.get("")
def catalog(
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    mapping = _mapping(db)
    doctors = db.query(Doctor).order_by(Doctor.id.asc()).all()
    visits = db.query(VisitType).order_by(VisitType.name.asc()).all()
    return {
        "doctors": [_doctor_payload(d, mapping.get(int(d.id), [])) for d in doctors],
        "visit_types": [_visit_payload(v) for v in visits],
    }

@router.post("/doctors")
def create_doctor(
    payload: DoctorIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    allowed = {k: v for k, v in payload.model_dump().items() if _has_column(Doctor, k)}
    row = Doctor(**allowed)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _doctor_payload(row, [])

@router.put("/doctors/{doctor_id}")
def update_doctor(
    doctor_id: int,
    payload: DoctorIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    row = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not row:
        raise HTTPException(404, "Medico non trovato")
    for key, value in payload.model_dump().items():
        if _has_column(Doctor, key):
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    mapping = _mapping(db)
    return _doctor_payload(row, mapping.get(int(row.id), []))

@router.post("/visit-types")
def create_visit_type(
    payload: VisitTypeIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    data = payload.model_dump()
    if not _has_column(VisitType, "color_hex") and _has_column(VisitType, "color"):
        data["color"] = data.pop("color_hex", None)
    allowed = {k: v for k, v in data.items() if _has_column(VisitType, k)}
    row = VisitType(**allowed)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _visit_payload(row)

@router.put("/visit-types/{visit_type_id}")
def update_visit_type(
    visit_type_id: int,
    payload: VisitTypeIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    row = db.query(VisitType).filter(VisitType.id == visit_type_id).first()
    if not row:
        raise HTTPException(404, "Tipologia visita non trovata")
    data = payload.model_dump()
    if not _has_column(VisitType, "color_hex") and _has_column(VisitType, "color"):
        data["color"] = data.pop("color_hex", None)
    for key, value in data.items():
        if _has_column(VisitType, key):
            setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _visit_payload(row)

@router.put("/doctors/{doctor_id}/visit-types")
def set_doctor_visit_types(
    doctor_id: int,
    payload: DoctorVisitTypesIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(404, "Medico non trovato")

    ids = sorted(set(int(x) for x in payload.visit_type_ids))
    if ids:
        existing = {int(v.id) for v in db.query(VisitType).filter(VisitType.id.in_(ids)).all()}
        missing = [x for x in ids if x not in existing]
        if missing:
            raise HTTPException(400, f"Tipologie visita non valide: {missing}")

    db.execute(text("DELETE FROM doctor_visit_types WHERE doctor_id=:doctor_id"), {"doctor_id": doctor_id})
    for visit_type_id in ids:
        db.execute(
            text("INSERT INTO doctor_visit_types(doctor_id, visit_type_id) VALUES (:doctor_id, :visit_type_id)"),
            {"doctor_id": doctor_id, "visit_type_id": visit_type_id},
        )
    db.commit()
    return {"status": "ok", "doctor_id": doctor_id, "visit_type_ids": ids}

@router.get("/doctor/{doctor_id}/visit-types")
def doctor_visit_types(
    doctor_id: int,
    current_user=Depends(require_role("admin", "operator")),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text(
            "SELECT v.id, v.name, v.duration_minutes, v.color_hex "
            "FROM visit_types v JOIN doctor_visit_types dvt ON dvt.visit_type_id=v.id "
            "WHERE dvt.doctor_id=:doctor_id ORDER BY v.name"
        ),
        {"doctor_id": doctor_id},
    ).mappings().all()
    return {"items": [dict(x) for x in rows]}
