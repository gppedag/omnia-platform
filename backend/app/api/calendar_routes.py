from __future__ import annotations
from datetime import datetime, date, time, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_

from app.auth import get_current_user, require_role
from app.db.database import get_db
from app.models.booking import Booking
from app.models.patient import Patient
from app.models.calendar import Doctor, VisitType, Agenda, AgendaRule, AgendaException
from app.schemas import DoctorCreate, VisitTypeCreate, AgendaCreate, CalendarBookingCreate, CalendarBookingUpdate
from app.services.visit_type_cleanup import normalize_service_name
from app.services.external_calendar import upsert_event, delete_event, test_provider
from app.services.reminder_service import ensure_booking_reminders, rebuild_future_reminders, cancel_future_reminders
from app.services.waitlist_service import create_offer_for_cancelled_booking
from app.services.previsit_service import ensure_previsit_for_booking

router = APIRouter(prefix='/api/calendar', tags=['calendar'])


def doctor_dict(d):
    return {'id': d.id, 'full_name': d.full_name,
        'color_hex': getattr(d, "color_hex", None),
        'color': getattr(d, "color_hex", None) or "#2563EB", 'specialty': d.specialty, 'email': d.email, 'phone': d.phone,
            'active': d.active, 'external_provider': d.external_provider, 'external_calendar_id': d.external_calendar_id,
            'external_calendar_user': d.external_calendar_user}

def visit_dict(v):
    return {'id': v.id, 'code': v.code, 'name': v.name, 'duration_minutes': v.duration_minutes,
        'color_hex': getattr(v, "color_hex", None),
        'color': (
            getattr(v, "color_hex", None)
            or getattr(v, "color", None)
            or "#0d6efd"
        ),
            'buffer_before_minutes': v.buffer_before_minutes, 'buffer_after_minutes': v.buffer_after_minutes,
            'color': v.color, 'active': v.active, 'notes': v.notes, 'recall_enabled': v.recall_enabled, 'recall_days': v.recall_days, 'followup_enabled': v.followup_enabled,
            'private_price_cents': v.private_price_cents or 0, 'ssn_enabled': bool(v.ssn_enabled), 'ssn_ticket_cents': v.ssn_ticket_cents or 0, 'requires_prescription': bool(v.requires_prescription)}

def agenda_dict(a):
    return {'id': a.id, 'name': a.name, 'doctor_id': a.doctor_id, 'doctor_name': a.doctor.full_name if a.doctor else None,
            'location': a.location, 'timezone': a.timezone, 'slot_minutes': a.slot_minutes, 'active': a.active,
            'visit_type_ids': [v.id for v in a.visit_types],
            'rules': [{'id': r.id, 'weekday': r.weekday, 'start_time': r.start_time.strftime('%H:%M'),
                       'end_time': r.end_time.strftime('%H:%M'), 'valid_from': str(r.valid_from) if r.valid_from else None,
                       'valid_to': str(r.valid_to) if r.valid_to else None, 'active': r.active} for r in a.rules]}

def booking_dict(b):
    return {'id': b.id, 'patient_id': b.patient_id, 'patient_name': (b.patient.user.full_name if b.patient and b.patient.user else None),
            'service_name': b.service_name, 'scheduled_at': b.scheduled_at, 'end_at': b.end_at,
            'status': b.status, 'priority': b.priority, 'notes': b.notes,
            'agenda_id': b.agenda_id, 'agenda_name': b.agenda.name if b.agenda else None,
            'visit_type_id': b.visit_type_id, 'visit_type_name': b.visit_type.name if b.visit_type else None,
            'visit_color': (
                getattr(b.visit_type, "color_hex", None)
                or getattr(b.visit_type, "color", None)
                or "#0d6efd"
            ) if b.visit_type else "#0d6efd",
            'doctor_color': (
                getattr(b.agenda.doctor, "color_hex", None)
                or "#2563EB"
            ) if b.agenda and b.agenda.doctor else "#2563EB",
            'doctor_ids': [d.id for d in b.doctors], 'doctor_names': [d.full_name for d in b.doctors],
            'external_provider': b.external_provider, 'external_event_id': b.external_event_id,
            'external_sync_status': b.external_sync_status, 'care_regime': getattr(b,'care_regime','private'), 'quoted_price_cents': getattr(b,'quoted_price_cents',0), 'source': getattr(b,'source','operator'), 'hold_expires_at': getattr(b,'hold_expires_at',None)}

@router.get('/doctors')
def list_doctors(active: Optional[bool] = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(Doctor)
    if active is not None: q = q.filter(Doctor.active == active)
    return [doctor_dict(x) for x in q.order_by(Doctor.full_name).all()]

@router.post('/doctors', status_code=201)
def create_doctor(payload: DoctorCreate, db: Session = Depends(get_db), user=Depends(require_role('admin'))):
    row = Doctor(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return doctor_dict(row)

@router.put('/doctors/{doctor_id}')
def update_doctor(doctor_id: int, payload: DoctorCreate, db: Session = Depends(get_db), user=Depends(require_role('admin'))):
    row = db.get(Doctor, doctor_id)
    if not row: raise HTTPException(404, 'Medico non trovato')
    for k,v in payload.model_dump().items(): setattr(row,k,v)
    db.commit(); db.refresh(row)
    return doctor_dict(row)

@router.get('/visit-types')
def list_visit_types(active: Optional[bool] = None, db: Session = Depends(get_db), user=Depends(get_current_user)):
    q=db.query(VisitType)
    if active is not None: q=q.filter(VisitType.active==active)
    return [visit_dict(x) for x in q.order_by(VisitType.name).all()]

@router.post('/visit-types', status_code=201)
def create_visit_type(payload: VisitTypeCreate, db: Session = Depends(get_db), user=Depends(require_role('admin'))):
    key = normalize_service_name(payload.name)
    existing = next((v for v in db.query(VisitType).all() if normalize_service_name(v.name) == key), None)
    if existing:
        raise HTTPException(409, f"La prestazione '{existing.name}' esiste già")
    row=VisitType(**payload.model_dump()); db.add(row); db.commit(); db.refresh(row); return visit_dict(row)

@router.put('/visit-types/{visit_id}')
def update_visit_type(visit_id:int,payload:VisitTypeCreate,db:Session=Depends(get_db),user=Depends(require_role('admin'))):
    row=db.get(VisitType,visit_id)
    if not row: raise HTTPException(404,'Tipologia visita non trovata')
    key = normalize_service_name(payload.name)
    duplicate = next((v for v in db.query(VisitType).filter(VisitType.id != visit_id).all() if normalize_service_name(v.name) == key), None)
    if duplicate:
        raise HTTPException(409, f"La prestazione '{duplicate.name}' esiste già")
    for k,v in payload.model_dump().items(): setattr(row,k,v)
    db.commit(); db.refresh(row); return visit_dict(row)

@router.get('/agendas')
def list_agendas(active:Optional[bool]=None,doctor_id:Optional[int]=None,db:Session=Depends(get_db),user=Depends(get_current_user)):
    q=db.query(Agenda).options(joinedload(Agenda.doctor),joinedload(Agenda.visit_types),joinedload(Agenda.rules))
    if active is not None:q=q.filter(Agenda.active==active)
    if doctor_id:q=q.filter(Agenda.doctor_id==doctor_id)
    return [agenda_dict(x) for x in q.order_by(Agenda.name).all()]

@router.post('/agendas',status_code=201)
def create_agenda(payload:AgendaCreate,db:Session=Depends(get_db),user=Depends(require_role('admin'))):
    if not db.get(Doctor,payload.doctor_id): raise HTTPException(400,'Medico non valido')
    row=Agenda(name=payload.name,doctor_id=payload.doctor_id,location=payload.location,timezone=payload.timezone,slot_minutes=payload.slot_minutes,active=payload.active)
    if payload.visit_type_ids: row.visit_types=db.query(VisitType).filter(VisitType.id.in_(payload.visit_type_ids)).all()
    db.add(row); db.flush()
    for r in payload.rules:
        st=time.fromisoformat(r.start_time); et=time.fromisoformat(r.end_time)
        if et<=st: raise HTTPException(400,'Orario agenda non valido')
        row.rules.append(AgendaRule(weekday=r.weekday,start_time=st,end_time=et,valid_from=r.valid_from,valid_to=r.valid_to,active=r.active))
    db.commit(); db.refresh(row); return agenda_dict(row)

@router.put('/agendas/{agenda_id}')
def update_agenda(agenda_id:int,payload:AgendaCreate,db:Session=Depends(get_db),user=Depends(require_role('admin'))):
    row=db.get(Agenda,agenda_id)
    if not row: raise HTTPException(404,'Agenda non trovata')
    row.name=payload.name; row.doctor_id=payload.doctor_id; row.location=payload.location; row.timezone=payload.timezone; row.slot_minutes=payload.slot_minutes; row.active=payload.active
    row.visit_types=db.query(VisitType).filter(VisitType.id.in_(payload.visit_type_ids)).all() if payload.visit_type_ids else []
    row.rules.clear(); db.flush()
    for r in payload.rules:
        row.rules.append(AgendaRule(weekday=r.weekday,start_time=time.fromisoformat(r.start_time),end_time=time.fromisoformat(r.end_time),valid_from=r.valid_from,valid_to=r.valid_to,active=r.active))
    db.commit(); db.refresh(row); return agenda_dict(row)

@router.get('/events')
def calendar_events(start:datetime,end:datetime,doctor_id:Optional[int]=None,agenda_id:Optional[int]=None,visit_type_id:Optional[int]=None,db:Session=Depends(get_db),user=Depends(get_current_user)):
    q=db.query(Booking).options(joinedload(Booking.patient),joinedload(Booking.doctors),joinedload(Booking.agenda),joinedload(Booking.visit_type)).filter(Booking.scheduled_at < end).filter((Booking.end_at > start) | ((Booking.end_at == None) & (Booking.scheduled_at >= start)))
    if agenda_id:q=q.filter(Booking.agenda_id==agenda_id)
    if visit_type_id:q=q.filter(Booking.visit_type_id==visit_type_id)
    if doctor_id:q=q.join(Booking.doctors).filter(Doctor.id==doctor_id)
    return [booking_dict(x) for x in q.order_by(Booking.scheduled_at).all()]


@router.get('/exceptions')
def calendar_exceptions(
    start: date,
    end: date,
    agenda_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    q = (
        db.query(AgendaException)
        .filter(
            AgendaException.date >= start,
            AgendaException.date <= end,
            AgendaException.kind == 'blocked'
        )
    )

    if agenda_id:
        q = q.filter(
            AgendaException.agenda_id == agenda_id
        )

    rows = q.order_by(
        AgendaException.date,
        AgendaException.start_time
    ).all()

    return [{
        'id': x.id,
        'agenda_id': x.agenda_id,
        'date': x.date,
        'start_time': (
            x.start_time.strftime('%H:%M')
            if x.start_time else None
        ),
        'end_time': (
            x.end_time.strftime('%H:%M')
            if x.end_time else None
        ),
        'kind': x.kind,
        'note': x.note
    } for x in rows]


@router.get('/slots')
def available_slots(day:date,agenda_id:int,visit_type_id:Optional[int]=None,db:Session=Depends(get_db),user=Depends(get_current_user)):
    agenda=db.query(Agenda).options(joinedload(Agenda.rules),joinedload(Agenda.visit_types)).filter(Agenda.id==agenda_id).first()
    if not agenda or not agenda.active: return []
    vt=db.get(VisitType,visit_type_id) if visit_type_id else None
    duration=(vt.duration_minutes if vt else agenda.slot_minutes)
    rules=[r for r in agenda.rules if r.active and r.weekday==day.weekday() and (not r.valid_from or r.valid_from<=day) and (not r.valid_to or r.valid_to>=day)]
    blocked=db.query(AgendaException).filter(AgendaException.agenda_id==agenda_id,AgendaException.date==day,AgendaException.kind=='blocked').all()
    start_day=datetime.combine(day,time.min); end_day=start_day+timedelta(days=1)
    expired=db.query(Booking).filter(Booking.agenda_id==agenda_id, Booking.status=='pending', Booking.hold_expires_at != None, Booking.hold_expires_at < datetime.now()).all()
    for b in expired: b.status='cancelled'
    if expired: db.commit()
    bookings=db.query(Booking).filter(Booking.agenda_id==agenda_id,Booking.status!='cancelled',Booking.scheduled_at<end_day).filter((Booking.end_at>start_day)|((Booking.end_at==None)&(Booking.scheduled_at>=start_day))).all()
    out=[]
    for r in rules:
        cur=datetime.combine(day,r.start_time); limit=datetime.combine(day,r.end_time)
        while cur+timedelta(minutes=duration)<=limit:
            finish=cur+timedelta(minutes=duration)
            conflict=any((b.end_at or (b.scheduled_at+timedelta(minutes=agenda.slot_minutes)))>cur and b.scheduled_at<finish for b in bookings)
            conflict=conflict or any((ex.start_time is None or datetime.combine(day,ex.start_time)<finish) and (ex.end_time is None or datetime.combine(day,ex.end_time)>cur) for ex in blocked)
            if not conflict: out.append({'start':cur,'end':finish})
            cur+=timedelta(minutes=agenda.slot_minutes)
    return out


# CUP_AVAILABILITY_SEARCH_V1
@router.get('/availability')
def availability_search(
    agenda_id: int,
    visit_type_id: int,
    from_day: date = Query(default_factory=date.today),
    days: int = Query(30, ge=1, le=90),
    max_dates: int = Query(7, ge=1, le=31),
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """
    Restituisce soltanto le prime giornate che hanno
    almeno uno slot realmente disponibile.
    """
    agenda = db.query(Agenda).options(
        joinedload(Agenda.rules),
        joinedload(Agenda.visit_types)
    ).filter(Agenda.id == agenda_id).first()

    if not agenda or not agenda.active:
        return []

    allowed_visit_ids = {v.id for v in agenda.visit_types}

    if visit_type_id not in allowed_visit_ids:
        raise HTTPException(
            400,
            'Prestazione non abilitata per questa agenda'
        )

    results = []

    for offset in range(days):
        current_day = from_day + timedelta(days=offset)

        slots = available_slots(
            day=current_day,
            agenda_id=agenda_id,
            visit_type_id=visit_type_id,
            db=db,
            user=user
        )

        if not slots:
            continue

        results.append({
            'date': current_day,
            'slots': slots
        })

        if len(results) >= max_dates:
            break

    return results

# /CUP_AVAILABILITY_SEARCH_V1


async def _sync_booking(row,db):
    if not row.doctors: return
    try:
        result=await upsert_event(row,row.patient,row.doctors)
        if result:
            row.external_provider,row.external_event_id=result; row.external_sync_status='synced'
        else: row.external_sync_status='local'
    except Exception as exc:
        row.external_sync_status='error: '+str(exc)[:180]
    db.commit(); db.refresh(row)

@router.post('/bookings',status_code=201)
async def create_calendar_booking(payload:CalendarBookingCreate,db:Session=Depends(get_db),user=Depends(require_role('admin','operator'))):
    patient=db.get(Patient,payload.patient_id)
    if not patient: raise HTTPException(400,'Paziente non valido')
    agenda=db.get(Agenda,payload.agenda_id) if payload.agenda_id else None
    vt=db.get(VisitType,payload.visit_type_id) if payload.visit_type_id else None
    doctors=db.query(Doctor).filter(Doctor.id.in_(payload.doctor_ids)).all() if payload.doctor_ids else ([] if not agenda else [agenda.doctor])
    if not doctors and agenda: doctors=[agenda.doctor]
    duration=(
        payload.duration_minutes
        if getattr(payload, "duration_minutes", None)
        else (
            vt.duration_minutes
            if vt
            else (
                agenda.slot_minutes
                if agenda
                else 60
            )
        )
    )
    row=Booking(patient_id=payload.patient_id,operator_id=getattr(user,'id',None),service_name=vt.name if vt else 'Visita',scheduled_at=payload.scheduled_at,end_at=payload.scheduled_at+timedelta(minutes=duration),agenda_id=payload.agenda_id,visit_type_id=payload.visit_type_id,priority=payload.priority,notes=payload.notes,status='confirmed')
    row.doctors=doctors
    # Evita sovrapposizioni sui medici associati.
    finish=row.end_at
    for d in doctors:
        conflict=db.query(Booking).join(Booking.doctors).filter(Doctor.id==d.id,Booking.status!='cancelled',Booking.scheduled_at<finish).filter((Booking.end_at>payload.scheduled_at)|((Booking.end_at==None)&(Booking.scheduled_at>=payload.scheduled_at))).first()
        if conflict: raise HTTPException(409,f'{d.full_name} risulta gia occupato in questo intervallo')
    db.add(row); db.commit(); db.refresh(row)
    row=db.query(Booking).options(joinedload(Booking.patient),joinedload(Booking.doctors),joinedload(Booking.agenda),joinedload(Booking.visit_type)).filter(Booking.id==row.id).first()
    if payload.sync_external: await _sync_booking(row,db)
    ensure_booking_reminders(db, row, include_confirmation=True)
    ensure_previsit_for_booking(db, row)
    return booking_dict(row)

@router.patch('/bookings/{booking_id}')
async def update_calendar_booking(booking_id:int,payload:CalendarBookingUpdate,db:Session=Depends(get_db),user=Depends(require_role('admin','operator'))):
    row=db.query(Booking).options(joinedload(Booking.patient),joinedload(Booking.doctors),joinedload(Booking.agenda),joinedload(Booking.visit_type)).filter(Booking.id==booking_id).first()
    if not row: raise HTTPException(404,'Prenotazione non trovata')
    data=payload.model_dump(exclude_unset=True)
    if 'agenda_id' in data: row.agenda_id=data['agenda_id']
    if 'visit_type_id' in data: row.visit_type_id=data['visit_type_id']
    if 'doctor_ids' in data: row.doctors=db.query(Doctor).filter(Doctor.id.in_(data['doctor_ids'])).all()
    if 'scheduled_at' in data: row.scheduled_at=data['scheduled_at']
    if 'priority' in data: row.priority=data['priority']
    if 'notes' in data: row.notes=data['notes']
    if 'status' in data: row.status=data['status']
    vt=db.get(VisitType,row.visit_type_id) if row.visit_type_id else None
    agenda=db.get(Agenda,row.agenda_id) if row.agenda_id else None
    duration=(
        payload.duration_minutes
        if getattr(payload, "duration_minutes", None)
        else (
            vt.duration_minutes
            if vt
            else (
                agenda.slot_minutes
                if agenda
                else 60
            )
        )
    )
    row.end_at=row.scheduled_at+timedelta(minutes=duration)
    if vt: row.service_name=vt.name
    db.commit(); db.refresh(row)
    if row.status=='cancelled':
        await delete_event(row,row.doctors); row.external_sync_status='cancelled'; db.commit(); cancel_future_reminders(db,row.id)
        create_offer_for_cancelled_booking(db, row)
    else:
        if payload.sync_external: await _sync_booking(row,db)
        rebuild_future_reminders(db,row)
        ensure_previsit_for_booking(db,row)
        if row.status == 'completed':
            from app.services.care_service import ensure_care_for_completed_booking
            ensure_care_for_completed_booking(db, row)
    return booking_dict(row)

@router.post('/bookings/{booking_id}/sync')
async def sync_booking(booking_id:int,db:Session=Depends(get_db),user=Depends(require_role('admin','operator'))):
    row=db.query(Booking).options(joinedload(Booking.patient),joinedload(Booking.doctors)).filter(Booking.id==booking_id).first()
    if not row: raise HTTPException(404,'Prenotazione non trovata')
    await _sync_booking(row,db)
    return booking_dict(row)

@router.post('/test/{provider}')
async def test_calendar_provider(provider:str,user=Depends(require_role('admin'))):
    try: return await test_provider(provider)
    except Exception as exc: return {'ok':False,'message':str(exc)}
