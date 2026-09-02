from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db.database import get_db

router = APIRouter(prefix="/api/admin/agenda-visits", tags=["admin-agenda-visits"])

class AgendaVisitTypesIn(BaseModel):
    visit_type_ids: list[int] = []

@router.get("")
def get_agenda_visit_matrix(
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    agendas = db.execute(text(
        "SELECT a.id,a.name,a.doctor_id,a.location,a.slot_minutes,a.active,"
        "d.full_name AS doctor_name,d.color_hex AS doctor_color "
        "FROM agendas a LEFT JOIN doctors d ON d.id=a.doctor_id ORDER BY a.name"
    )).mappings().all()

    agenda_rows = db.execute(text(
        "SELECT agenda_id,visit_type_id FROM agenda_visit_types "
        "ORDER BY agenda_id,visit_type_id"
    )).all()

    doctor_rows = db.execute(text(
        "SELECT doctor_id,visit_type_id FROM doctor_visit_types "
        "ORDER BY doctor_id,visit_type_id"
    )).all()

    visits = db.execute(text(
        "SELECT id,code,name,duration_minutes,color_hex,active "
        "FROM visit_types ORDER BY name"
    )).mappings().all()

    by_agenda = {}
    for agenda_id, visit_type_id in agenda_rows:
        by_agenda.setdefault(int(agenda_id), []).append(int(visit_type_id))

    by_doctor = {}
    for doctor_id, visit_type_id in doctor_rows:
        by_doctor.setdefault(int(doctor_id), []).append(int(visit_type_id))

    result = []
    for agenda in agendas:
        row = dict(agenda)
        row["visit_type_ids"] = by_agenda.get(int(agenda["id"]), [])
        row["doctor_visit_type_ids"] = (
            by_doctor.get(int(agenda["doctor_id"]), [])
            if agenda["doctor_id"] is not None else []
        )
        result.append(row)

    return {"agendas": result, "visit_types": [dict(v) for v in visits]}

@router.put("/{agenda_id}")
def update_agenda_visit_types(
    agenda_id: int,
    payload: AgendaVisitTypesIn,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    agenda = db.execute(
        text("SELECT id,name,doctor_id FROM agendas WHERE id=:agenda_id"),
        {"agenda_id": agenda_id},
    ).mappings().first()

    if not agenda:
        raise HTTPException(status_code=404, detail="Agenda non trovata")

    ids = sorted(set(int(x) for x in payload.visit_type_ids))
    doctor_id = agenda["doctor_id"]

    if doctor_id is None and ids:
        raise HTTPException(
            status_code=409,
            detail="Assegna prima un medico all'agenda.",
        )

    if doctor_id is not None and ids:
        enabled = {
            int(row[0])
            for row in db.execute(
                text(
                    "SELECT visit_type_id FROM doctor_visit_types "
                    "WHERE doctor_id=:doctor_id"
                ),
                {"doctor_id": doctor_id},
            ).all()
        }

        invalid = [x for x in ids if x not in enabled]

        if invalid:
            names = [
                row[0]
                for row in db.execute(
                    text(
                        "SELECT name FROM visit_types "
                        "WHERE id = ANY(:ids) ORDER BY name"
                    ),
                    {"ids": invalid},
                ).all()
            ]

            raise HTTPException(
                status_code=409,
                detail=(
                    "Prestazioni non abilitate per il medico "
                    "associato all'agenda: " + ", ".join(names)
                ),
            )

    db.execute(
        text("DELETE FROM agenda_visit_types WHERE agenda_id=:agenda_id"),
        {"agenda_id": agenda_id},
    )

    for visit_type_id in ids:
        db.execute(
            text(
                "INSERT INTO agenda_visit_types(agenda_id,visit_type_id) "
                "VALUES (:agenda_id,:visit_type_id)"
            ),
            {"agenda_id": agenda_id, "visit_type_id": visit_type_id},
        )

    db.commit()

    return {
        "status": "ok",
        "agenda_id": agenda_id,
        "visit_type_ids": ids,
    }
