from __future__ import annotations
import json
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from app.auth import get_current_user, require_role
from app.db.database import get_db
from app.models.booking import Booking
from app.models.patient import Patient
from app.models.previsit import PreVisitTemplate, PreVisitSubmission, BookingCheckIn
from app.services.previsit_service import ensure_previsit_for_booking, resolve_token, previsit_url, checkin_url, serialize_submission

router = APIRouter(prefix="/api/previsit", tags=["previsit"])

class TemplateIn(BaseModel):
    name: str
    visit_type_id: Optional[int] = None
    fields: list[dict] = []
    consent_title: str = "Consenso informato e privacy"
    consent_text: str = ""
    required: bool = True
    active: bool = True

class PublicSubmission(BaseModel):
    token: str
    answers: dict
    consent_accepted: bool
    consent_name: str

class CheckInAction(BaseModel):
    token: str

class StatusIn(BaseModel):
    status: str
    notes: Optional[str] = None


def _booking_query(db, booking_id):
    return db.query(Booking).options(joinedload(Booking.patient).joinedload(Patient.user), joinedload(Booking.doctors)).filter(Booking.id == booking_id).first()

@router.get("/templates")
def templates(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = db.query(PreVisitTemplate).order_by(PreVisitTemplate.name).all()
    return [{"id":x.id,"name":x.name,"visit_type_id":x.visit_type_id,"fields":json.loads(x.form_json or "[]"),"consent_title":x.consent_title,"consent_text":x.consent_text,"required":x.required,"active":x.active} for x in rows]

@router.post("/templates", status_code=201)
def create_template(payload: TemplateIn, db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    row=PreVisitTemplate(name=payload.name,visit_type_id=payload.visit_type_id,form_json=json.dumps(payload.fields,ensure_ascii=False),consent_title=payload.consent_title,consent_text=payload.consent_text,required=payload.required,active=payload.active)
    db.add(row); db.commit(); db.refresh(row); return {"id":row.id}

@router.put("/templates/{template_id}")
def update_template(template_id:int,payload:TemplateIn,db:Session=Depends(get_db),user=Depends(require_role("admin"))):
    row=db.get(PreVisitTemplate,template_id)
    if not row: raise HTTPException(404,"Template non trovato")
    row.name=payload.name; row.visit_type_id=payload.visit_type_id; row.form_json=json.dumps(payload.fields,ensure_ascii=False); row.consent_title=payload.consent_title; row.consent_text=payload.consent_text; row.required=payload.required; row.active=payload.active
    db.commit(); return {"ok":True}

@router.get("/submissions")
def submissions(status:Optional[str]=None,db:Session=Depends(get_db),user=Depends(get_current_user)):
    q=db.query(PreVisitSubmission).options(joinedload(PreVisitSubmission.booking).joinedload(Booking.patient).joinedload(Patient.user))
    if status: q=q.filter(PreVisitSubmission.status==status)
    return [serialize_submission(x) for x in q.order_by(PreVisitSubmission.created_at.desc()).limit(300).all()]

@router.post("/booking/{booking_id}/prepare")
def prepare(booking_id:int,db:Session=Depends(get_db),user=Depends(require_role("admin","operator"))):
    b=_booking_query(db,booking_id)
    if not b: raise HTTPException(404,"Prenotazione non trovata")
    row=ensure_previsit_for_booking(db,b)
    return {"ok":bool(row),"previsit_url":previsit_url(booking_id),"checkin_url":checkin_url(booking_id)}

@router.get("/public")
def public_get(token:str,db:Session=Depends(get_db)):
    try: bid=resolve_token(token,"previsit")
    except ValueError as exc: raise HTTPException(400,str(exc))
    b=_booking_query(db,bid)
    if not b: raise HTTPException(404,"Prenotazione non trovata")
    row=ensure_previsit_for_booking(db,b)
    if not row: raise HTTPException(404,"Pre-visita non disponibile")
    t=row.template
    return {"booking_id":b.id,"patient_name":getattr(b.patient.user,"full_name",None),"service_name":b.service_name,"scheduled_at":b.scheduled_at,"status":row.status,"fields":json.loads(t.form_json or "[]"),"consent_title":t.consent_title,"consent_text":t.consent_text}

@router.post("/public/submit")
def public_submit(payload:PublicSubmission,db:Session=Depends(get_db)):
    try: bid=resolve_token(payload.token,"previsit")
    except ValueError as exc: raise HTTPException(400,str(exc))
    b=_booking_query(db,bid)
    if not b: raise HTTPException(404,"Prenotazione non trovata")
    row=ensure_previsit_for_booking(db,b)
    if row.template.required and not payload.consent_accepted: raise HTTPException(400,"Consenso obbligatorio")
    row.answers_json=json.dumps(payload.answers,ensure_ascii=False); row.consent_accepted=payload.consent_accepted; row.consent_name=payload.consent_name; row.consent_at=datetime.utcnow() if payload.consent_accepted else None; row.status="completed"; row.completed_at=datetime.utcnow(); db.commit()
    return {"ok":True,"message":"Pre-visita completata"}

@router.get("/checkins")
def checkins(day:Optional[str]=None,db:Session=Depends(get_db),user=Depends(get_current_user)):
    q=db.query(BookingCheckIn).options(joinedload(BookingCheckIn.booking).joinedload(Booking.patient).joinedload(Patient.user))
    if day:
        try:
            d=datetime.fromisoformat(day).date(); start=datetime.combine(d,datetime.min.time()); end=start+timedelta(days=1); q=q.join(Booking).filter(Booking.scheduled_at>=start,Booking.scheduled_at<end)
        except Exception: pass
    out=[]
    for x in q.order_by(BookingCheckIn.updated_at.desc()).limit(300).all():
        b=x.booking; out.append({"id":x.id,"booking_id":x.booking_id,"status":x.status,"patient_name":getattr(getattr(b.patient,"user",None),"full_name",None),"service_name":b.service_name,"scheduled_at":b.scheduled_at,"checked_in_at":x.checked_in_at,"notes":x.notes})
    return out

@router.patch("/checkins/{checkin_id}")
def checkin_status(checkin_id:int,payload:StatusIn,db:Session=Depends(get_db),user=Depends(require_role("admin","operator"))):
    allowed={"not_arrived","checked_in","waiting","in_visit","completed","no_show"}
    if payload.status not in allowed: raise HTTPException(400,"Stato non valido")
    row=db.get(BookingCheckIn,checkin_id)
    if not row: raise HTTPException(404,"Check-in non trovato")
    row.status=payload.status; row.notes=payload.notes
    now=datetime.utcnow()
    if payload.status=="checked_in": row.checked_in_at=now
    elif payload.status=="waiting": row.waiting_at=now
    elif payload.status=="in_visit": row.in_visit_at=now
    elif payload.status=="completed": row.completed_at=now
    db.commit(); return {"ok":True}

@router.get("/checkin/public")
def checkin_public(token:str,db:Session=Depends(get_db)):
    try: bid=resolve_token(token,"checkin")
    except ValueError as exc: raise HTTPException(400,str(exc))
    b=_booking_query(db,bid)
    if not b: raise HTTPException(404,"Prenotazione non trovata")
    row=db.query(BookingCheckIn).filter(BookingCheckIn.booking_id==bid).first()
    if not row: row=BookingCheckIn(booking_id=bid,status="not_arrived"); db.add(row); db.commit(); db.refresh(row)
    return {"booking_id":bid,"patient_name":getattr(b.patient.user,"full_name",None),"service_name":b.service_name,"scheduled_at":b.scheduled_at,"status":row.status}

@router.post("/checkin/public")
def checkin_public_action(payload:CheckInAction,db:Session=Depends(get_db)):
    try: bid=resolve_token(payload.token,"checkin")
    except ValueError as exc: raise HTTPException(400,str(exc))
    b=_booking_query(db,bid)
    if not b: raise HTTPException(404,"Prenotazione non trovata")
    now=datetime.utcnow()
    early=b.scheduled_at-timedelta(hours=6); late=b.scheduled_at+timedelta(hours=4)
    if now < early or now > late: raise HTTPException(409,"Check-in disponibile solo in prossimità dell'appuntamento")
    row=db.query(BookingCheckIn).filter(BookingCheckIn.booking_id==bid).first()
    if not row: row=BookingCheckIn(booking_id=bid)
    row.status="checked_in"; row.source="patient_link"; row.checked_in_at=now; db.add(row); db.commit()
    return {"ok":True,"message":"Check-in registrato"}


# CUP_PREVISIT_DETAIL_V1

@router.get("/submissions/{submission_id}")
def submission_detail(
    submission_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = (
        db.query(PreVisitSubmission)
        .options(
            joinedload(PreVisitSubmission.booking)
                .joinedload(Booking.patient)
                .joinedload(Patient.user),
            joinedload(PreVisitSubmission.template),
        )
        .filter(
            PreVisitSubmission.id == submission_id
        )
        .first()
    )

    if not row:
        raise HTTPException(
            404,
            "Pre-visita non trovata"
        )

    booking = row.booking
    template = row.template

    try:
        answers = json.loads(
            row.answers_json or "{}"
        )
    except Exception:
        answers = {}

    try:
        fields = json.loads(
            template.form_json or "[]"
        ) if template else []
    except Exception:
        fields = []

    return {
        "id": row.id,
        "booking_id": row.booking_id,
        "status": row.status,

        "patient_name": (
            getattr(
                getattr(
                    getattr(booking, "patient", None),
                    "user",
                    None
                ),
                "full_name",
                None
            )
        ),

        "service_name": (
            booking.service_name
            if booking else None
        ),

        "scheduled_at": (
            booking.scheduled_at
            if booking else None
        ),

        "completed_at": row.completed_at,

        "consent_accepted":
            bool(row.consent_accepted),

        "consent_name":
            row.consent_name,

        "consent_at":
            row.consent_at,

        "template_name": (
            template.name
            if template else None
        ),

        "fields": fields,
        "answers": answers,
    }

# /CUP_PREVISIT_DETAIL_V1
