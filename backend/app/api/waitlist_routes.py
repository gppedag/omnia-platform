from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user, require_role
from app.db.database import get_db
from app.models.waitlist import WaitlistEntry, WaitlistOffer, WaitlistOfferRecipient
from app.models.patient import Patient
from app.services.waitlist_service import resolve_token, accept_offer

router = APIRouter(prefix='/api/waitlist', tags=['waitlist'])

class WaitlistCreate(BaseModel):
    patient_id: int
    visit_type_id: Optional[int] = None
    agenda_id: Optional[int] = None
    doctor_id: Optional[int] = None
    preferred_from: Optional[datetime] = None
    preferred_to: Optional[datetime] = None
    preferred_time_from: Optional[str] = None
    preferred_time_to: Optional[str] = None
    priority: int = 0
    channels: Optional[str] = None
    notes: Optional[str] = None


def entry_dict(e):
    return {'id':e.id,'patient_id':e.patient_id,'patient_name':e.patient.user.full_name if e.patient and e.patient.user else None,
            'visit_type_id':e.visit_type_id,'visit_type_name':e.visit_type.name if e.visit_type else None,
            'agenda_id':e.agenda_id,'agenda_name':e.agenda.name if e.agenda else None,
            'doctor_id':e.doctor_id,'doctor_name':e.doctor.full_name if e.doctor else None,
            'preferred_from':e.preferred_from,'preferred_to':e.preferred_to,'preferred_time_from':e.preferred_time_from,
            'preferred_time_to':e.preferred_time_to,'priority':e.priority,'channels':e.channels,'status':e.status,'notes':e.notes,'created_at':e.created_at}

@router.get('')
def list_entries(db:Session=Depends(get_db),user=Depends(get_current_user)):
    rows=db.query(WaitlistEntry).options(joinedload(WaitlistEntry.patient).joinedload(Patient.user),joinedload(WaitlistEntry.visit_type),joinedload(WaitlistEntry.agenda),joinedload(WaitlistEntry.doctor)).order_by(WaitlistEntry.status,WaitlistEntry.priority.desc(),WaitlistEntry.created_at).all()
    return [entry_dict(x) for x in rows]

@router.post('',status_code=201)
def create_entry(payload:WaitlistCreate,db:Session=Depends(get_db),user=Depends(require_role('admin','operator'))):
    if not db.get(Patient,payload.patient_id): raise HTTPException(400,'Paziente non valido')
    row=WaitlistEntry(**payload.model_dump(),status='waiting'); db.add(row); db.commit(); db.refresh(row)
    row=db.query(WaitlistEntry).options(joinedload(WaitlistEntry.patient).joinedload(Patient.user),joinedload(WaitlistEntry.visit_type),joinedload(WaitlistEntry.agenda),joinedload(WaitlistEntry.doctor)).filter(WaitlistEntry.id==row.id).first()
    return entry_dict(row)

@router.patch('/{entry_id}/status')
def status(entry_id:int,status:str,db:Session=Depends(get_db),user=Depends(require_role('admin','operator'))):
    if status not in {'waiting','paused','cancelled'}: raise HTTPException(400,'Stato non valido')
    row=db.get(WaitlistEntry,entry_id)
    if not row: raise HTTPException(404,'Voce non trovata')
    row.status=status; db.commit(); return {'ok':True,'status':status}

@router.get('/offers')
def offers(db:Session=Depends(get_db),user=Depends(get_current_user)):
    rows=db.query(WaitlistOffer).options(joinedload(WaitlistOffer.recipients)).order_by(WaitlistOffer.created_at.desc()).limit(50).all()
    return [{'id':o.id,'scheduled_at':o.scheduled_at,'expires_at':o.expires_at,'status':o.status,'agenda_id':o.agenda_id,'visit_type_id':o.visit_type_id,'accepted_booking_id':o.accepted_booking_id,'recipients':len(o.recipients)} for o in rows]

@router.get('/public/offer')
def public_offer(token:str,db:Session=Depends(get_db)):
    try: tid=resolve_token(token)
    except ValueError as e: raise HTTPException(400,str(e))
    rec=db.query(WaitlistOfferRecipient).options(joinedload(WaitlistOfferRecipient.offer).joinedload(WaitlistOffer.agenda),joinedload(WaitlistOfferRecipient.offer).joinedload(WaitlistOffer.visit_type),joinedload(WaitlistOfferRecipient.patient).joinedload(Patient.user)).filter(WaitlistOfferRecipient.token_id==tid).first()
    if not rec: raise HTTPException(404,'Proposta non trovata')
    o=rec.offer
    return {'status':rec.status,'offer_status':o.status,'expires_at':o.expires_at,'scheduled_at':o.scheduled_at,'agenda':o.agenda.name if o.agenda else None,'visit':o.visit_type.name if o.visit_type else 'Visita','patient':rec.patient.user.full_name if rec.patient and rec.patient.user else None}

@router.post('/public/accept')
def public_accept(token:str,db:Session=Depends(get_db)):
    try:
        b=accept_offer(db,token)
        return {'ok':True,'booking_id':b.id,'scheduled_at':b.scheduled_at,'service_name':b.service_name}
    except ValueError as e: raise HTTPException(409,str(e))
