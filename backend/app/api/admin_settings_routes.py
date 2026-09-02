from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db.database import get_db

router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])


class DoctorIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    specialty: str | None = None
    email: str | None = None
    color_hex: str = "#2563EB"
    active: bool = True


class VisitTypeIn(BaseModel):
    code: str | None = None
    name: str = Field(min_length=2, max_length=200)
    duration_minutes: int = Field(default=60, ge=5, le=480)
    color_hex: str = "#3B82F6"
    active: bool = True


class AgendaIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    doctor_id: int | None = None
    location: str | None = None
    slot_minutes: int = Field(default=60, ge=5, le=480)
    active: bool = True


@router.get("")
def get_settings(
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    doctors = db.execute(
        text(
            """
            SELECT id, full_name, specialty, email, color_hex, active
            FROM doctors
            ORDER BY full_name
            """
        )
    ).mappings().all()

    visits = db.execute(
        text(
            """
            SELECT id, code, name, duration_minutes, color_hex, active
            FROM visit_types
            ORDER BY name
            """
        )
    ).mappings().all()

    agendas = db.execute(
        text(
            """
            SELECT
                a.id,
                a.name,
                a.doctor_id,
                a.location,
                a.slot_minutes,
                a.active,
                d.full_name AS doctor_name,
                d.color_hex AS doctor_color
            FROM agendas a
            LEFT JOIN doctors d ON d.id=a.doctor_id
            ORDER BY a.name
            """
        )
    ).mappings().all()

    return {
        "doctors": [dict(x) for x in doctors],
        "visit_types": [dict(x) for x in visits],
        "agendas": [dict(x) for x in agendas],
    }


@router.post("/doctors")
def create_doctor(
    payload: DoctorIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    row = db.execute(
        text(
            """
            INSERT INTO doctors(
                full_name,
                specialty,
                email,
                color_hex,
                active
            )
            VALUES(
                :full_name,
                :specialty,
                :email,
                :color_hex,
                :active
            )
            RETURNING id
            """
        ),
        payload.model_dump(),
    ).first()

    db.commit()
    return {"status": "ok", "id": int(row[0])}


@router.put("/doctors/{doctor_id}")
def update_doctor(
    doctor_id: int,
    payload: DoctorIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    exists = db.execute(
        text("SELECT 1 FROM doctors WHERE id=:id"),
        {"id": doctor_id},
    ).first()

    if not exists:
        raise HTTPException(404, "Medico non trovato")

    values = payload.model_dump()
    values["id"] = doctor_id

    db.execute(
        text(
            """
            UPDATE doctors
            SET
                full_name=:full_name,
                specialty=:specialty,
                email=:email,
                color_hex=:color_hex,
                active=:active
            WHERE id=:id
            """
        ),
        values,
    )

    db.commit()
    return {"status": "ok", "id": doctor_id}


@router.post("/visit-types")
def create_visit_type(
    payload: VisitTypeIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    row = db.execute(
        text(
            """
            INSERT INTO visit_types(
                code,
                name,
                duration_minutes,
                color_hex,
                active
            )
            VALUES(
                :code,
                :name,
                :duration_minutes,
                :color_hex,
                :active
            )
            RETURNING id
            """
        ),
        payload.model_dump(),
    ).first()

    db.commit()
    return {"status": "ok", "id": int(row[0])}


@router.put("/visit-types/{visit_type_id}")
def update_visit_type(
    visit_type_id: int,
    payload: VisitTypeIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    exists = db.execute(
        text("SELECT 1 FROM visit_types WHERE id=:id"),
        {"id": visit_type_id},
    ).first()

    if not exists:
        raise HTTPException(404, "Prestazione non trovata")

    values = payload.model_dump()
    values["id"] = visit_type_id

    db.execute(
        text(
            """
            UPDATE visit_types
            SET
                code=:code,
                name=:name,
                duration_minutes=:duration_minutes,
                color_hex=:color_hex,
                active=:active
            WHERE id=:id
            """
        ),
        values,
    )

    db.commit()
    return {"status": "ok", "id": visit_type_id}


@router.post("/agendas")
def create_agenda(
    payload: AgendaIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if payload.doctor_id is not None:
        doctor = db.execute(
            text("SELECT 1 FROM doctors WHERE id=:id"),
            {"id": payload.doctor_id},
        ).first()

        if not doctor:
            raise HTTPException(400, "Medico non valido")

    row = db.execute(
        text(
            """
            INSERT INTO agendas(
                name,
                doctor_id,
                location,
                slot_minutes,
                active
            )
            VALUES(
                :name,
                :doctor_id,
                :location,
                :slot_minutes,
                :active
            )
            RETURNING id
            """
        ),
        payload.model_dump(),
    ).first()

    db.commit()
    return {"status": "ok", "id": int(row[0])}


@router.put("/agendas/{agenda_id}")
def update_agenda(
    agenda_id: int,
    payload: AgendaIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    exists = db.execute(
        text("SELECT 1 FROM agendas WHERE id=:id"),
        {"id": agenda_id},
    ).first()

    if not exists:
        raise HTTPException(404, "Agenda non trovata")

    if payload.doctor_id is not None:
        doctor = db.execute(
            text("SELECT 1 FROM doctors WHERE id=:id"),
            {"id": payload.doctor_id},
        ).first()

        if not doctor:
            raise HTTPException(400, "Medico non valido")

    values = payload.model_dump()
    values["id"] = agenda_id

    db.execute(
        text(
            """
            UPDATE agendas
            SET
                name=:name,
                doctor_id=:doctor_id,
                location=:location,
                slot_minutes=:slot_minutes,
                active=:active
            WHERE id=:id
            """
        ),
        values,
    )

    db.commit()
    return {"status": "ok", "id": agenda_id}
