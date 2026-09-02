from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.auth import require_role
from app.config import settings
from app.db.database import get_db
from app.models.booking import Booking
from app.models.care import PostVisitFollowup, RecallCampaign
from app.models.patient import Patient
from app.services.care_service import resolve_followup_token, resolve_recall_token, followup_url, recall_url, send_followup, send_recall, ensure_care_for_completed_booking

router = APIRouter(prefix="/api/care", tags=["care"])


def _followup_dict(x):
    return {"id":x.id,"booking_id":x.booking_id,"patient_id":x.patient_id,"patient_name":x.patient.user.full_name if x.patient and x.patient.user else None,
        "service_name":x.booking.service_name if x.booking else None,"scheduled_for":x.scheduled_for,"status":x.status,"channel":x.channel,"attempts":x.attempts,
        "rating":x.rating,"wellbeing":x.wellbeing,"needs_contact":x.needs_contact,"comment":x.comment,"sent_at":x.sent_at,"completed_at":x.completed_at}


def _recall_dict(x):
    return {"id":x.id,"source_booking_id":x.source_booking_id,"patient_id":x.patient_id,"patient_name":x.patient.user.full_name if x.patient and x.patient.user else None,
        "service_name":x.source_booking.service_name if x.source_booking else None,"due_at":x.due_at,"status":x.status,"channel":x.channel,"attempts":x.attempts,
        "sent_at":x.sent_at,"booked_booking_id":x.booked_booking_id,"snoozed_until":x.snoozed_until}


@router.get("/followups")
def list_followups(db:Session=Depends(get_db), user=Depends(require_role("admin","operator"))):
    rows=db.query(PostVisitFollowup).options(joinedload(PostVisitFollowup.patient).joinedload(Patient.user),joinedload(PostVisitFollowup.booking)).order_by(PostVisitFollowup.scheduled_for.desc()).limit(300).all()
    return [_followup_dict(x) for x in rows]

@router.get("/recalls")
def list_recalls(db:Session=Depends(get_db), user=Depends(require_role("admin","operator"))):
    rows=db.query(RecallCampaign).options(joinedload(RecallCampaign.patient).joinedload(Patient.user),joinedload(RecallCampaign.source_booking)).order_by(RecallCampaign.due_at.asc()).limit(300).all()
    return [_recall_dict(x) for x in rows]

@router.post("/booking/{booking_id}/prepare")
def prepare(booking_id:int, db:Session=Depends(get_db), user=Depends(require_role("admin","operator"))):
    b=db.query(Booking).options(joinedload(Booking.patient),joinedload(Booking.visit_type)).filter(Booking.id==booking_id).first()
    if not b: raise HTTPException(404,"Appuntamento non trovato")
    ensure_care_for_completed_booking(db,b)
    f=db.query(PostVisitFollowup).filter(PostVisitFollowup.booking_id==b.id).first(); r=db.query(RecallCampaign).filter(RecallCampaign.source_booking_id==b.id).first()
    return {"ok":True,"followup_id":f.id if f else None,"recall_id":r.id if r else None}

@router.patch("/followups/{row_id}/resolve")
def resolve_followup(row_id:int, db:Session=Depends(get_db), user=Depends(require_role("admin","operator"))):
    row=db.get(PostVisitFollowup,row_id)
    if not row: raise HTTPException(404,"Follow-up non trovato")
    row.status="completed"; row.needs_contact=False
    if not row.completed_at: row.completed_at=datetime.now()
    db.commit(); return {"ok":True,"status":row.status}


@router.post("/followups/{row_id}/send")
def send_followup_now(row_id:int, db:Session=Depends(get_db), user=Depends(require_role("admin","operator"))):
    row=db.get(PostVisitFollowup,row_id)
    if not row: raise HTTPException(404,"Follow-up non trovato")
    if row.status in {"completed","needs_contact"}: raise HTTPException(409,"Follow-up gia completato")
    row.status="scheduled"; db.commit(); send_followup(db,row); return {"ok":True,"status":row.status}

@router.post("/recalls/{row_id}/send")
def send_recall_now(row_id:int, db:Session=Depends(get_db), user=Depends(require_role("admin","operator"))):
    row=db.get(RecallCampaign,row_id)
    if not row: raise HTTPException(404,"Recall non trovato")
    if row.status in {"booked","completed","cancelled"}: raise HTTPException(409,"Recall non inviabile")
    row.status="due"; db.commit(); send_recall(db,row); return {"ok":True,"status":row.status}

@router.patch("/recalls/{row_id}/snooze")
def snooze_recall(row_id:int, days:int=30, db:Session=Depends(get_db), user=Depends(require_role("admin","operator"))):
    row=db.get(RecallCampaign,row_id)
    if not row: raise HTTPException(404,"Recall non trovato")
    row.snoozed_until=datetime.now()+timedelta(days=max(1,min(days,365))); row.due_at=row.snoozed_until; row.status="snoozed"; db.commit()
    return {"ok":True,"due_at":row.due_at}

class FollowupAnswer(BaseModel):
    rating:int=Field(ge=1,le=5)
    wellbeing:str
    needs_contact:bool=False
    comment:str|None=None

@router.get("/public/followup/{token}")
def public_followup(token:str, db:Session=Depends(get_db)):
    try: row_id,jti=resolve_followup_token(token)
    except ValueError as exc: raise HTTPException(400,str(exc))
    row=db.query(PostVisitFollowup).options(joinedload(PostVisitFollowup.patient).joinedload(Patient.user),joinedload(PostVisitFollowup.booking)).filter(PostVisitFollowup.id==row_id).first()
    if not row or row.token_id!=jti: raise HTTPException(404,"Follow-up non trovato")
    return {"id":row.id,"status":row.status,"patient_name":row.patient.user.full_name if row.patient and row.patient.user else None,"service_name":row.booking.service_name if row.booking else None,"date":row.booking.scheduled_at if row.booking else None}

@router.post("/public/followup/{token}")
def submit_followup(token:str,payload:FollowupAnswer,db:Session=Depends(get_db)):
    try: row_id,jti=resolve_followup_token(token)
    except ValueError as exc: raise HTTPException(400,str(exc))
    row=db.get(PostVisitFollowup,row_id)
    if not row or row.token_id!=jti: raise HTTPException(404,"Follow-up non trovato")
    row.rating=payload.rating; row.wellbeing=payload.wellbeing; row.needs_contact=payload.needs_contact; row.comment=payload.comment; row.completed_at=datetime.now(); row.status="needs_contact" if payload.needs_contact or payload.wellbeing=="worse" else "completed"; db.commit()
    return {"ok":True,"status":row.status}

@router.get("/public/recall/{token}")
def public_recall(token:str,db:Session=Depends(get_db)):
    try: row_id,jti=resolve_recall_token(token)
    except ValueError as exc: raise HTTPException(400,str(exc))
    row=db.query(RecallCampaign).options(joinedload(RecallCampaign.patient).joinedload(Patient.user),joinedload(RecallCampaign.source_booking)).filter(RecallCampaign.id==row_id).first()
    if not row or row.token_id!=jti: raise HTTPException(404,"Recall non trovato")
    service=row.source_booking.service_name if row.source_booking else "controllo"
    mode=settings.BOOKING_MODE
    if mode=="external": action_url=settings.EXTERNAL_BOOKING_URL
    else:
        base=settings.CUP_PUBLIC_BASE_URL.rstrip("/")
        action_url=(base if base else "")+f"/chatbot.html?prefill=Vorrei%20prenotare%20{service.replace(' ','%20')}"
    return {"id":row.id,"status":row.status,"patient_name":row.patient.user.full_name if row.patient and row.patient.user else None,"service_name":service,"due_at":row.due_at,"booking_mode":mode,"action_url":action_url}
