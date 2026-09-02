from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db.database import get_db

router = APIRouter(prefix="/api/calendar-eligibility", tags=["calendar-eligibility"])

@router.get("")
def eligibility(
    visit_type_id: int | None = None,
    doctor_id: int | None = None,
    current_user=Depends(require_role("operator", "admin")),
    db: Session = Depends(get_db),
):
    where = []
    params = {}
    if visit_type_id is not None:
        where.append("dvt.visit_type_id=:visit_type_id")
        params["visit_type_id"] = visit_type_id
    if doctor_id is not None:
        where.append("dvt.doctor_id=:doctor_id")
        params["doctor_id"] = doctor_id
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    query = (
        "SELECT dvt.doctor_id,dvt.visit_type_id,d.full_name AS doctor_name,"
        "d.color_hex AS doctor_color,v.name AS visit_name,"
        "v.color_hex AS visit_color,v.duration_minutes "
        "FROM doctor_visit_types dvt "
        "JOIN doctors d ON d.id=dvt.doctor_id "
        "JOIN visit_types v ON v.id=dvt.visit_type_id" + clause +
        " ORDER BY d.full_name,v.name"
    )
    rows = db.execute(text(query), params).mappings().all()
    doctor_ids = sorted({int(x["doctor_id"]) for x in rows})
    visit_type_ids = sorted({int(x["visit_type_id"]) for x in rows})
    agendas = []
    if visit_type_id is not None:
        agendas = db.execute(text(
            "SELECT a.id,a.name,a.doctor_id,a.location,a.slot_minutes "
            "FROM agendas a WHERE a.active=TRUE AND a.doctor_id IN ("
            "SELECT doctor_id FROM doctor_visit_types WHERE visit_type_id=:visit_type_id"
            ") ORDER BY a.name"
        ), {"visit_type_id": visit_type_id}).mappings().all()
    return {
        "items":[dict(x) for x in rows],
        "doctor_ids":doctor_ids,
        "visit_type_ids":visit_type_ids,
        "agendas":[dict(x) for x in agendas],
    }
