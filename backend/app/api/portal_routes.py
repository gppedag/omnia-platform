from __future__ import annotations
from jose import JWTError, jwt

from datetime import datetime, timedelta, time
from pathlib import Path
from secrets import token_urlsafe
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.db.database import get_db
from app.models.user import User
from app.models.patient import Patient
from app.models.calendar import VisitType, Agenda, AgendaException
from app.models.booking import Booking
from app.models.portal import PatientPortalSession, PatientDocument, QueueTicket, PortalSupportRequest, PatientDocumentShare
from app.models.commerce import PaymentRequest
from app.services.reminder_service import ensure_booking_reminders
from app.services.previsit_service import ensure_previsit_for_booking
from app.services.visit_type_cleanup import normalize_service_name


portal_bearer = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/api/portal", tags=["patient-portal"])

PORTAL_UPLOAD_DIR = Path("/data/uploads/portal")
PORTAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class HoldRequest(BaseModel):
    token: str
    visit_type_id: int
    agenda_id: int
    scheduled_at: datetime
    regime: str = "private"


class QueueCheckInRequest(BaseModel):
    token: str
    booking_id: int


class SupportRequestIn(BaseModel):
    token: Optional[str] = None
    phone: Optional[str] = None
    fiscal_code: Optional[str] = None
    message: str


def _portal_session(db: Session, token: str) -> PatientPortalSession:
    row = db.query(PatientPortalSession).options(joinedload(PatientPortalSession.patient).joinedload(Patient.user)).filter(PatientPortalSession.token == token).first()
    if not row or row.expires_at < datetime.now():
        raise HTTPException(401, "Sessione portale scaduta")
    return row


def _price(v: VisitType, regime: str) -> int:
    if regime == "ssn":
        if not v.ssn_enabled:
            raise HTTPException(400, "Prestazione non disponibile in regime SSN")
        return int(v.ssn_ticket_cents or 0)
    if regime != "private":
        raise HTTPException(400, "Regime non valido")
    return int(v.private_price_cents or 0)


def _demo_pdf(path: Path, title: str, subtitle: str) -> None:
    safe_title = title.replace("(", "[").replace(")", "]")[:70]
    safe_sub = subtitle.replace("(", "[").replace(")", "]")[:95]
    stream = f"BT /F1 18 Tf 72 760 Td ({safe_title}) Tj 0 -36 Td /F1 11 Tf ({safe_sub}) Tj ET".encode("latin-1", "replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n"); offsets=[0]
    for i,obj in enumerate(objs,1):
        offsets.append(len(out)); out += f"{i} 0 obj\n".encode()+obj+b"\nendobj\n"
    xref=len(out); out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for off in offsets[1:]: out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


def _ensure_demo_patient(db: Session) -> Patient:
    patient = db.query(Patient).join(User).filter(User.email.like("demo.cup+%@example.test")).order_by(Patient.id).first()
    if not patient:
        user = User(email="demo.cup+portal@example.test", hashed_password="demo-not-used", full_name="Giulia Ferri", role="patient", phone="+39 333 555 0101", is_active=True)
        db.add(user); db.flush()
        patient = Patient(user_id=user.id, fiscal_code="FRRGLI85A41F205X", reminder_enabled="true", reminder_channels="sms,email")
        db.add(patient); db.commit(); db.refresh(patient)
    return patient


def _ensure_demo_documents(db: Session, patient: Patient) -> None:
    if db.query(PatientDocument).filter(PatientDocument.patient_id == patient.id).count():
        return
    docs = [
        ("report", "Referto visita cardiologica", "Referto demo - nessun dato sanitario reale."),
        ("invoice", "Documento fiscale n. DEMO-2026-001", "Documento fiscale sintetico per demo CUP."),
        ("form", "Istruzioni preparazione esame", "Presentarsi 15 minuti prima con richiesta medica."),
    ]
    for idx, (cat,title,subtitle) in enumerate(docs,1):
        path=PORTAL_UPLOAD_DIR / f"demo-patient-{patient.id}-{idx}.pdf"
        _demo_pdf(path,title,subtitle)
        db.add(PatientDocument(patient_id=patient.id, category=cat, title=title, filename=path.name, stored_path=str(path), mime_type="application/pdf", status="available"))
    db.commit()


def _slot_is_free(db: Session, agenda: Agenda, start: datetime, duration: int) -> bool:
    finish = start + timedelta(minutes=duration)
    conflict = db.query(Booking).filter(
        Booking.agenda_id == agenda.id,
        Booking.status != "cancelled",
        Booking.scheduled_at < finish,
    ).filter((Booking.end_at > start) | ((Booking.end_at == None) & (Booking.scheduled_at >= start))).first()
    if conflict:
        if conflict.status == "pending" and conflict.hold_expires_at and conflict.hold_expires_at < datetime.now():
            conflict.status = "cancelled"; db.commit()
        else:
            return False
    blocked = db.query(AgendaException).filter(AgendaException.agenda_id == agenda.id, AgendaException.date == start.date(), AgendaException.kind == "blocked").all()
    for ex in blocked:
        ex_start = datetime.combine(start.date(), ex.start_time) if ex.start_time else datetime.combine(start.date(), time.min)
        ex_end = datetime.combine(start.date(), ex.end_time) if ex.end_time else datetime.combine(start.date(), time.max)
        if ex_start < finish and ex_end > start:
            return False
    return True




@router.post("/session")
def create_patient_portal_session(
    credentials: HTTPAuthorizationCredentials = Depends(portal_bearer),
    db: Session = Depends(get_db),
):
    """
    Converte un JWT paziente autenticato via OTP
    in una PatientPortalSession.
    """

    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Autenticazione richiesta",
        )

    try:
        token_data = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Sessione di autenticazione non valida o scaduta",
        )

    if token_data.get("role") != "patient":
        raise HTTPException(
            status_code=403,
            detail="Accesso consentito solo ai pazienti",
        )

    try:
        user_id = int(token_data.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Identità utente non valida",
        )

    user = db.get(User, user_id)

    if not user or not user.is_active or user.role != "patient":
        raise HTTPException(
            status_code=403,
            detail="Account paziente non disponibile",
        )

    if getattr(user, "account_status", None) == "suspended":
        raise HTTPException(
            status_code=403,
            detail="Account sospeso",
        )

    patient = (
        db.query(Patient)
        .filter(Patient.user_id == user.id)
        .first()
    )

    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Profilo paziente non trovato",
        )

    token = token_urlsafe(36)

    row = PatientPortalSession(
        patient_id=patient.id,
        token=token,
        expires_at=datetime.now() + timedelta(hours=12),
    )

    db.add(row)
    db.commit()

    return {
        "token": token,
        "expires_in": 43200,
        "patient": {
            "id": patient.id,
            "full_name": user.full_name,
            "fiscal_code": patient.fiscal_code,
            "phone": user.phone,
            "email": user.email,
            "identity_status": getattr(
                patient,
                "identity_status",
                None,
            ),
        },
    }


@router.post("/demo-session")
def demo_session(db: Session = Depends(get_db)):
    if not settings.DEMO_DATA_ENABLED and not settings.DEV_ROLE_LOGIN_ENABLED:
        raise HTTPException(403, "Accesso guest disponibile solo in modalità demo")
    patient = _ensure_demo_patient(db)
    _ensure_demo_documents(db, patient)
    token = token_urlsafe(36)
    row = PatientPortalSession(patient_id=patient.id, token=token, expires_at=datetime.now()+timedelta(hours=12))
    db.add(row); db.commit()
    return {"token": token, "patient": {"id": patient.id, "full_name": patient.user.full_name, "fiscal_code": patient.fiscal_code, "phone": patient.user.phone}}


@router.get("/catalog")
def catalog(db: Session = Depends(get_db)):
    visits = db.query(VisitType).filter(VisitType.active == True).order_by(VisitType.name, VisitType.id).all()
    # Safety net for upgraded databases: never expose duplicate services in the patient portal.
    unique = {}
    for v in visits:
        key = normalize_service_name(v.name)
        current = unique.get(key)
        if current is None or ((current.code or "").upper().startswith("CUP") and not (v.code or "").upper().startswith("CUP")):
            unique[key] = v
    return [{
        "id": v.id, "code": v.code, "name": v.name, "duration_minutes": v.duration_minutes, "color_hex": getattr(v, "color_hex", None),
        "private_price_cents": int(v.private_price_cents or 0), "ssn_enabled": bool(v.ssn_enabled),
        "ssn_ticket_cents": int(v.ssn_ticket_cents or 0), "requires_prescription": bool(v.requires_prescription),
        "notes": v.notes,
    } for v in sorted(unique.values(), key=lambda x: (x.name or "").lower())]


@router.get("/next-slots")
def next_slots(visit_type_id: int, regime: str = "private", days: Optional[int] = Query(None, ge=1, le=365), limit: int = Query(18, ge=1, le=40), db: Session = Depends(get_db)):
    visit = db.get(VisitType, visit_type_id)
    if not visit or not visit.active: raise HTTPException(404, "Prestazione non trovata")
    price_cents = _price(visit, regime)
    # Patient-facing horizon: several weeks for private care, several months for SSN.
    search_days = days if days is not None else (240 if regime == "ssn" else 56)
    agendas = db.query(Agenda).options(joinedload(Agenda.rules), joinedload(Agenda.doctor), joinedload(Agenda.visit_types)).filter(Agenda.active == True).all()
    agendas = [a for a in agendas if any(v.id == visit.id for v in a.visit_types)]
    out=[]; now=datetime.now()
    for offset in range(search_days):
        day=(now+timedelta(days=offset)).date()
        for agenda in agendas:
            rules=[r for r in agenda.rules if r.active and r.weekday==day.weekday() and (not r.valid_from or r.valid_from<=day) and (not r.valid_to or r.valid_to>=day)]
            for rule in rules:
                cur=datetime.combine(day,rule.start_time); end=datetime.combine(day,rule.end_time)
                while cur+timedelta(minutes=visit.duration_minutes)<=end:
                    if cur > now + timedelta(minutes=30) and _slot_is_free(db,agenda,cur,visit.duration_minutes):
                        out.append({"agenda_id":agenda.id,"agenda_name":agenda.name,"doctor_id":agenda.doctor_id,"doctor_name":agenda.doctor.full_name if agenda.doctor else None, "doctor_color": (agenda.doctor.color_hex if agenda and agenda.doctor else None),"location":agenda.location,"start":cur.isoformat(),"end":(cur+timedelta(minutes=visit.duration_minutes)).isoformat(),"regime":regime,"price_cents":price_cents,"search_horizon_days":search_days})
                        if len(out)>=limit: return sorted(out,key=lambda x:x["start"])
                    cur += timedelta(minutes=max(5,agenda.slot_minutes))
    return sorted(out,key=lambda x:x["start"])


@router.post("/bookings/hold")
def hold_booking(payload: HoldRequest, db: Session = Depends(get_db)):
    session=_portal_session(db,payload.token); visit=db.get(VisitType,payload.visit_type_id); agenda=db.get(Agenda,payload.agenda_id)
    if not visit or not agenda or not visit.active or not agenda.active: raise HTTPException(400,"Prestazione o agenda non valida")
    if not any(v.id == visit.id for v in agenda.visit_types): raise HTTPException(400,"Prestazione non abilitata su questa agenda")
    price=_price(visit,payload.regime)
    start=payload.scheduled_at.replace(tzinfo=None) if payload.scheduled_at.tzinfo else payload.scheduled_at
    # lock rows for this agenda during the collision check
    db.query(Agenda).filter(Agenda.id==agenda.id).with_for_update().first()
    if not _slot_is_free(db,agenda,start,visit.duration_minutes): raise HTTPException(409,"Lo slot non è più disponibile")
    row=Booking(patient_id=session.patient_id, service_name=visit.name, scheduled_at=start, end_at=start+timedelta(minutes=visit.duration_minutes), agenda_id=agenda.id, visit_type_id=visit.id, status="pending", priority="normal", care_regime=payload.regime, quoted_price_cents=price, hold_expires_at=datetime.now()+timedelta(minutes=15), source="patient_portal", notes="Richiesta online - attesa conferma operatore")
    if agenda.doctor: row.doctors=[agenda.doctor]
    db.add(row); db.commit(); db.refresh(row)
    ensure_booking_reminders(db,row,include_confirmation=True)
    ensure_previsit_for_booking(db,row)
    return {"ok":True,"booking_id":row.id,"status":row.status,"hold_expires_at":row.hold_expires_at,"price_cents":price,"message":"Slot bloccato. La richiesta è stata inviata al CUP per conferma."}


@router.get("/dashboard")
def dashboard(token: str, db: Session = Depends(get_db)):
    session=_portal_session(db,token); patient=session.patient
    bookings=db.query(Booking).options(joinedload(Booking.agenda).joinedload(Agenda.doctor),joinedload(Booking.visit_type)).filter(Booking.patient_id==patient.id).order_by(Booking.scheduled_at.desc()).limit(30).all()
    docs=db.query(PatientDocument).filter(PatientDocument.patient_id==patient.id).order_by(PatientDocument.created_at.desc()).all()
    tickets=db.query(QueueTicket).filter(QueueTicket.patient_id==patient.id).order_by(QueueTicket.created_at.desc()).limit(10).all()
    payments=db.query(PaymentRequest).filter(PaymentRequest.patient_id==patient.id).order_by(PaymentRequest.created_at.desc()).limit(20).all()
    now=datetime.now()
    return {
        "patient":{"id":patient.id,"full_name":patient.user.full_name if patient.user else "Paziente","fiscal_code":patient.fiscal_code,"phone":patient.user.phone if patient.user else None},
        "bookings":[{"id":b.id,"service_name":b.service_name,"scheduled_at":b.scheduled_at,"status":b.status,"doctor_name":b.agenda.doctor.full_name if b.agenda and b.agenda.doctor else None, "doctor_color": (b.agenda.doctor.color_hex if b.agenda and b.agenda.doctor else None),"location":b.agenda.location if b.agenda else None,"regime":b.care_regime or "private","price_cents":b.quoted_price_cents or 0,"hold_expires_at":b.hold_expires_at,"requires_prescription":bool(b.visit_type.requires_prescription) if b.visit_type else False,"expired_hold":bool(b.status=="pending" and b.hold_expires_at and b.hold_expires_at<now)} for b in bookings],
        "documents":[{"id":d.id,"category":d.category,"title":d.title,"filename":d.filename,"status":d.status,"created_at":d.created_at} for d in docs],
        "queue":[{"id":q.id,"booking_id":q.booking_id,"code":q.code,"status":q.status,"estimated_wait_minutes":q.estimated_wait_minutes,"checked_in_at":q.checked_in_at,"called_at":q.called_at} for q in tickets],
        "payments":[{"id":x.id,"description":x.description,"amount_cents":x.amount_cents,"currency":x.currency,"provider":x.provider,"status":x.status,"checkout_url":x.checkout_url,"due_at":x.due_at,"paid_at":x.paid_at,"created_at":x.created_at} for x in payments],
    }


@router.post("/queue/check-in")
def queue_check_in(payload: QueueCheckInRequest, db: Session = Depends(get_db)):
    session=_portal_session(db,payload.token); booking=db.query(Booking).filter(Booking.id==payload.booking_id,Booking.patient_id==session.patient_id).first()
    if not booking: raise HTTPException(404,"Prenotazione non trovata")
    existing=db.query(QueueTicket).filter(QueueTicket.booking_id==booking.id,QueueTicket.status.in_(["waiting","called"])).first()
    if existing: return {"id":existing.id,"code":existing.code,"status":existing.status,"estimated_wait_minutes":existing.estimated_wait_minutes}
    waiting=db.query(QueueTicket).filter(QueueTicket.status=="waiting").count()
    ticket=QueueTicket(patient_id=session.patient_id,booking_id=booking.id,code=f"A{100+waiting+1}",status="waiting",estimated_wait_minutes=max(5,(waiting+1)*8),checked_in_at=datetime.now())
    db.add(ticket); db.commit(); db.refresh(ticket)
    return {"id":ticket.id,"code":ticket.code,"status":ticket.status,"estimated_wait_minutes":ticket.estimated_wait_minutes}


@router.get("/documents/{document_id}/download")
def download_document(document_id: int, token: str, db: Session = Depends(get_db)):
    session=_portal_session(db,token); doc=db.query(PatientDocument).filter(PatientDocument.id==document_id,PatientDocument.patient_id==session.patient_id).first()
    if not doc: raise HTTPException(404,"Documento non trovato")
    path=Path(doc.stored_path)
    if not path.exists(): raise HTTPException(404,"File non disponibile")
    return FileResponse(str(path),media_type=doc.mime_type,filename=doc.filename)


@router.post("/documents/{document_id}/share")
def share_document(document_id: int, token: str, db: Session = Depends(get_db)):
    session=_portal_session(db,token); doc=db.query(PatientDocument).filter(PatientDocument.id==document_id,PatientDocument.patient_id==session.patient_id).first()
    if not doc: raise HTTPException(404,"Documento non trovato")
    share_token=token_urlsafe(32); code=str(100000 + __import__('secrets').randbelow(900000))
    share=PatientDocumentShare(document_id=doc.id,token=share_token,access_code=code,expires_at=datetime.now()+timedelta(hours=24))
    db.add(share); db.commit()
    return {"url":f"/api/portal/shared/{share_token}","access_code":code,"expires_at":share.expires_at}


@router.get("/shared/{share_token}")
def download_shared_document(share_token: str, code: str, db: Session = Depends(get_db)):
    share=db.query(PatientDocumentShare).options(joinedload(PatientDocumentShare.document)).filter(PatientDocumentShare.token==share_token).first()
    if not share or share.expires_at < datetime.now() or share.access_code != str(code).strip(): raise HTTPException(403,"Link o codice non valido/scaduto")
    path=Path(share.document.stored_path)
    if not path.exists(): raise HTTPException(404,"File non disponibile")
    return FileResponse(str(path),media_type=share.document.mime_type,filename=share.document.filename)


@router.post("/support")
def support(payload: SupportRequestIn, db: Session = Depends(get_db)):
    patient_id=None
    if payload.token:
        try: patient_id=_portal_session(db,payload.token).patient_id
        except HTTPException: patient_id=None
    msg=(payload.message or "").strip()
    if len(msg)<5: raise HTTPException(400,"Descrivi brevemente la richiesta")
    row=PortalSupportRequest(patient_id=patient_id,phone=payload.phone,fiscal_code=payload.fiscal_code,message=msg,status="open")
    db.add(row); db.commit(); db.refresh(row)
    return {"ok":True,"request_id":row.id,"message":"Richiesta presa in carico. Un operatore ti ricontatterà."}
