from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timedelta, time
from uuid import uuid4

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models.user import User
from app.models.patient import Patient
from app.models.calendar import Doctor, VisitType, Agenda, AgendaRule
from app.models.booking import Booking
from app.models.call import Call
from app.models.chat import ChatSession, ChatMessage
from app.models.omnichannel import ConversationChannel, HandoffEvent
from app.models.handoff import OperatorHandoff
from app.models.reminder import AppointmentReminder
from app.models.waitlist import WaitlistEntry, WaitlistOffer, WaitlistOfferRecipient
from app.models.previsit import PreVisitTemplate, PreVisitSubmission, BookingCheckIn
from app.models.care import PostVisitFollowup, RecallCampaign
from app.models.commerce import PaymentRequest, SignatureRequest
from app.models.training import AILearningSample
from app.config import settings
from app.services.signature_service import ensure_dir, sha256_bytes

from app.services.previsit_service import ensure_default_templates

DEMO_PREFIX = "demo.cup+"


def _at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    now = datetime.now()
    d = (now + timedelta(days=day_offset)).date()
    return datetime.combine(d, time(hour, minute))


def _ensure_analytics_demo_history(db: Session, patients, agendas, visits) -> int:
    """Aggiunge uno storico sintetico per rendere leggibili gli analytics demo."""
    if not patients or not agendas or not visits:
        return 0
    note = "Demo analytics storico v1.0.21"
    existing = db.query(Booking).filter(Booking.notes == note).count()
    if existing >= 18:
        return 0
    created = 0
    channels = ["web", "whatsapp", "telegram"]
    for idx in range(existing, 18):
        day = -(3 + idx)
        patient = patients[idx % len(patients)]
        visit = visits[idx % len(visits)]
        agenda = agendas[idx % len(agendas)]
        start = _at(day, 9 + (idx % 7), 0 if idx % 2 == 0 else 30)
        status = "cancelled" if idx in {5, 13} else "completed"
        b = Booking(patient_id=patient.id, service_name=visit.name, scheduled_at=start,
                    end_at=start + timedelta(minutes=visit.duration_minutes or 30), agenda_id=agenda.id,
                    visit_type_id=visit.id, status=status, priority="normal", notes=note)
        if getattr(agenda, "doctor", None):
            b.doctors = [agenda.doctor]
        db.add(b); db.flush(); created += 1
        if status != "cancelled":
            ci_status = "no_show" if idx in {4, 11, 17} else "completed"
            db.add(BookingCheckIn(booking_id=b.id, status=ci_status, source="operator",
                                  completed_at=start + timedelta(minutes=visit.duration_minutes or 30) if ci_status == "completed" else None))
            db.add(AppointmentReminder(booking_id=b.id, kind="reminder", offset_hours=24, channel="sms",
                                       target=patient.user.phone if patient.user else None, scheduled_for=start-timedelta(hours=24),
                                       status="failed" if idx in {7, 15} else "sent", attempts=1,
                                       sent_at=start-timedelta(hours=24) if idx not in {7,15} else None,
                                       provider_response="Demo analytics"))
        # Sessioni AI: circa meta' convertono in prenotazione.
        sid = str(uuid4())
        ctx = {"step": "complete" if idx % 2 == 0 else "llm", "demo": True}
        if idx % 2 == 0:
            ctx["booking_id"] = b.id
        ch = channels[idx % len(channels)]
        db.add(ChatSession(id=sid, channel=ch, sender_id=patient.user.phone if patient.user else None, status="bot", context_json=json.dumps(ctx)))
        db.add(ConversationChannel(session_id=sid, channel=ch, external_id=f"demo-analytics-{ch}-{idx}-{sid[:6]}", display_name=patient.user.full_name if patient.user else "Demo"))
        db.add(ChatMessage(session_id=sid, role="user", content="Richiesta demo analytics"))
    db.commit()
    return created



def _demo_pdf_bytes() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length 91 >>\nstream\nBT /F1 18 Tf 72 760 Td (Documento demo CUP - consenso informato) Tj 0 -36 Td /F1 11 Tf (Documento sintetico per collaudo firma.) Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out)); out.extend(f"{i} 0 obj\n".encode()); out.extend(obj); out.extend(b"\nendobj\n")
    xref = len(out); out.extend(f"xref\n0 {len(objects)+1}\n".encode()); out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]: out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(out)


def _ensure_commerce_demo(db: Session, patients, bookings) -> int:
    if not patients:
        return 0
    created = 0
    demo_payment = db.query(PaymentRequest).filter(PaymentRequest.description.like("Demo CUP:%")).count()
    if demo_payment == 0:
        db.add(PaymentRequest(patient_id=patients[0].id, booking_id=bookings[0].id if bookings else None, description="Demo CUP: acconto visita", amount_cents=4500, currency="EUR", provider="manual", status="sent", channels="sms,email", sent_at=datetime.now()-timedelta(hours=3), provider_response="Demo: richiesta inviata")); created += 1
        db.add(PaymentRequest(patient_id=patients[1].id, booking_id=bookings[1].id if len(bookings)>1 else None, description="Demo CUP: saldo prestazione", amount_cents=9000, currency="EUR", provider="manual", status="paid", channels="email", sent_at=datetime.now()-timedelta(days=1), paid_at=datetime.now()-timedelta(hours=6), provider_response="Demo: pagamento ricevuto")); created += 1
    if db.query(SignatureRequest).filter(SignatureRequest.title.like("Demo CUP:%")).count() == 0:
        ensure_dir(); raw = _demo_pdf_bytes(); path = str(Path(settings.SIGNATURE_UPLOAD_DIR) / "demo-consenso-cup.pdf")
        Path(path).write_bytes(raw); digest = sha256_bytes(raw)
        db.add(SignatureRequest(patient_id=patients[2].id, booking_id=bookings[2].id if len(bookings)>2 else None, title="Demo CUP: consenso informato", message="Documento dimostrativo da leggere e firmare.", original_filename="consenso-demo.pdf", stored_path=path, document_sha256=digest, status="sent", channels="sms,email", sent_at=datetime.now()-timedelta(hours=2), expires_at=datetime.now()+timedelta(days=7))); created += 1
        db.add(SignatureRequest(patient_id=patients[3].id, booking_id=bookings[3].id if len(bookings)>3 else None, title="Demo CUP: autorizzazione trattamento", message="Documento dimostrativo già firmato.", original_filename="autorizzazione-demo.pdf", stored_path=path, document_sha256=digest, status="signed", channels="email", signer_name=patients[3].user.full_name, signature_sha256=sha256_bytes(b"demo-signature"), signed_ip="127.0.0.1", signed_user_agent="CUP demo", sent_at=datetime.now()-timedelta(days=1), viewed_at=datetime.now()-timedelta(hours=20), signed_at=datetime.now()-timedelta(hours=19), expires_at=datetime.now()+timedelta(days=7))); created += 1
    db.commit(); return created


def _ensure_demo_staff(db: Session):
    specs = [
        ("admin@demo.cup", "Admin Demo CUP", "admin", "AdminDemo123!", True, True),
        ("operatore@demo.cup", "Operatore Demo CUP", "operator", "OperatorDemo123!", True, True),
    ]
    made = 0
    for email, name, role, password, can_chat, can_phone in specs:
        row = db.query(User).filter(User.email == email).first()
        if not row:
            row = User(email=email, full_name=name, role=role, hashed_password=hash_password(password), is_active=True, can_chat=can_chat, can_phone=can_phone)
            db.add(row); made += 1
        else:
            # Gli account demo esistenti mantengono la password impostata
            # dall'amministratore. Il seed riallinea solo profilo e permessi.
            row.full_name=name; row.role=role; row.is_active=True; row.can_chat=can_chat; row.can_phone=can_phone
    db.flush()
    if db.query(AILearningSample).count() == 0:
        op = db.query(User).filter(User.email == "operatore@demo.cup").first()
        db.add(AILearningSample(source_type="chat", operator_id=op.id if op else None, consent_obtained=True,
            user_text="Vorrei spostare la visita, quali disponibilità avete?",
            operator_text="Verifico subito gli slot liberi e ti propongo le prime alternative disponibili.",
            anonymized_user_text="Vorrei spostare la visita, quali disponibilità avete?",
            anonymized_operator_text="Verifico subito gli slot liberi e ti propongo le prime alternative disponibili.",
            status="approved", review_notes="Esempio demo del metodo CUP", reviewed_by=None, reviewed_at=datetime.now()))
        made += 1
    db.commit()
    return made


def seed_demo_data(db: Session, force: bool = False) -> dict:
    """Crea un dataset dimostrativo idempotente senza toccare dati reali.

    Se force=False e sono gia presenti utenti demo, non duplica i record.
    Tutte le anagrafiche demo hanno email con prefisso demo.cup+.
    """
    staff_created = _ensure_demo_staff(db)
    existing = db.query(User).filter(User.email.like(f"{DEMO_PREFIX}%")).count()
    if existing and not force:
        demo_patient_rows = db.query(Patient).join(User).filter(User.email.like(f"{DEMO_PREFIX}%")).order_by(Patient.id).all()
        demo_patients = len(demo_patient_rows)
        if demo_patients >= 8:
            existing_wait = db.query(WaitlistEntry).filter(WaitlistEntry.patient_id.in_([p.id for p in demo_patient_rows])).count()
            if existing_wait < 3:
                # Upgrade non distruttivo del dataset demo v1.0.17 -> v1.0.18.
                visits_existing = db.query(VisitType).order_by(VisitType.id).all()
                agendas_existing = db.query(Agenda).order_by(Agenda.id).all()
                if visits_existing and agendas_existing:
                    demo_specs = [(demo_patient_rows[5], visits_existing[0], agendas_existing[0], 20), (demo_patient_rows[6], visits_existing[0], agendas_existing[0], 10), (demo_patient_rows[7], visits_existing[min(3,len(visits_existing)-1)], agendas_existing[min(1,len(agendas_existing)-1)], 0)]
                    made=[]
                    for pat,vis,ag,prio in demo_specs:
                        w=WaitlistEntry(patient_id=pat.id,visit_type_id=vis.id,agenda_id=ag.id,doctor_id=ag.doctor_id,preferred_from=_at(0,0,0),preferred_to=_at(14,23,59),preferred_time_from='09:00',preferred_time_to='18:00',priority=prio,channels='sms,email',status='waiting',notes='Demo lista d attesa automatica')
                        db.add(w); db.flush(); made.append(w)
                    slot=_at(4,12,0); offer=WaitlistOffer(agenda_id=agendas_existing[0].id,visit_type_id=visits_existing[0].id,scheduled_at=slot,end_at=slot+timedelta(minutes=getattr(visits_existing[0],'duration_minutes',30) or 30),status='open',expires_at=datetime.now()+timedelta(minutes=20))
                    db.add(offer); db.flush(); made[0].status='offered'
                    db.add(WaitlistOfferRecipient(offer_id=offer.id,waitlist_entry_id=made[0].id,patient_id=made[0].patient_id,token_id=uuid4().hex,channel='sms',target=made[0].patient.user.phone,status='offered',provider_response='Demo: proposta simulata',sent_at=datetime.now()))
                    db.commit()
                    existing_wait = 3
            ensure_default_templates(db)
            demo_bookings = db.query(Booking).filter(Booking.patient_id.in_([p.id for p in demo_patient_rows])).order_by(Booking.scheduled_at).all()
            created_pre = 0
            for idx, b in enumerate(demo_bookings):
                if not db.query(PreVisitSubmission).filter(PreVisitSubmission.booking_id == b.id).first():
                    tmpl = db.query(PreVisitTemplate).filter((PreVisitTemplate.visit_type_id == b.visit_type_id) | (PreVisitTemplate.visit_type_id == None)).first()
                    if tmpl:
                        status = "completed" if idx % 3 == 0 else "pending"
                        db.add(PreVisitSubmission(booking_id=b.id, template_id=tmpl.id, status=status, answers_json=json.dumps({"reason":"Controllo periodico demo","medications":"Nessuno"}, ensure_ascii=False) if status == "completed" else "{}", consent_accepted=(status == "completed"), consent_name=b.patient.user.full_name if status == "completed" else None, consent_at=datetime.now() if status == "completed" else None, completed_at=datetime.now() if status == "completed" else None))
                        created_pre += 1
                if not db.query(BookingCheckIn).filter(BookingCheckIn.booking_id == b.id).first():
                    cstatus = "checked_in" if b.scheduled_at.date() == datetime.now().date() and b.scheduled_at.hour <= datetime.now().hour + 1 and idx % 2 == 0 else "not_arrived"
                    db.add(BookingCheckIn(booking_id=b.id, status=cstatus, source="patient_link" if cstatus == "checked_in" else "operator", checked_in_at=datetime.now() if cstatus == "checked_in" else None))
            # Upgrade v1.0.20: aggiunge continuità di cura senza duplicare il dataset.
            created_care = 0
            completed_demo = [b for b in demo_bookings if b.status == "completed"]
            for b in completed_demo:
                if not db.query(PostVisitFollowup).filter(PostVisitFollowup.booking_id == b.id).first():
                    db.add(PostVisitFollowup(booking_id=b.id, patient_id=b.patient_id, scheduled_for=datetime.now()-timedelta(hours=2), status="needs_contact", channel="sms", target=b.patient.user.phone, attempts=1, provider_response="Demo: risposta ricevuta", sent_at=datetime.now()-timedelta(hours=20), completed_at=datetime.now()-timedelta(hours=18), rating=3, wellbeing="same", needs_contact=True, comment="Vorrei chiarire la terapia prescritta.", token_id=uuid4().hex)); created_care += 1
                if not db.query(RecallCampaign).filter(RecallCampaign.source_booking_id == b.id).first():
                    db.add(RecallCampaign(source_booking_id=b.id, patient_id=b.patient_id, visit_type_id=b.visit_type_id, due_at=datetime.now()+timedelta(days=30), status="scheduled", token_id=uuid4().hex)); created_care += 1
            if demo_bookings and not db.query(RecallCampaign).filter(RecallCampaign.patient_id==demo_bookings[0].patient_id, RecallCampaign.source_booking_id==None).first():
                src=demo_bookings[0]; db.add(RecallCampaign(source_booking_id=None, patient_id=src.patient_id, visit_type_id=src.visit_type_id, due_at=datetime.now()-timedelta(days=2), status="sent", channel="whatsapp", target=src.patient.user.phone, attempts=1, provider_response="Demo: consegnato", sent_at=datetime.now()-timedelta(days=1), token_id=uuid4().hex)); created_care += 1
            # Analytics demo legacy disabilitato: il modello corrente
            # applica i vincoli Agenda <-> Prestazione <-> Medico.
            analytics_created = 0
            commerce_created = _ensure_commerce_demo(db, demo_patient_rows, demo_bookings)
            db.commit()
            return {"ok": True, "created": bool(created_pre or created_care or analytics_created or commerce_created), "message": "Dataset demo aggiornato" if (created_pre or created_care or analytics_created or commerce_created) else "Dataset demo gia presente", "demo_users": existing, "patients": demo_patients, "waitlist": existing_wait, "previsit": len(demo_bookings), "care": created_care, "analytics_history": analytics_created, "commerce": commerce_created}
        # Ripara automaticamente seed parziali delle release precedenti.
        force = True

    # Non cancelliamo mai dati reali. In modalita force rimuoviamo solo i demo users;
    # i Patient collegati vengono eliminati in cascade, insieme alle booking demo.
    if force and existing:
        demo_users = db.query(User).filter(User.email.like(f"{DEMO_PREFIX}%")).all()
        for u in demo_users:
            db.delete(u)
        db.commit()

    # Medici / tipologie / agende: riusa record con stessi nomi per evitare duplicati.
    doctor_specs = [
        ("Dott.ssa Laura Bianchi", "Cardiologia", "laura.bianchi@demo.local", "google"),
        ("Dott. Marco Rinaldi", "Dermatologia", "marco.rinaldi@demo.local", "microsoft365"),
        ("Dott.ssa Sara Conti", "Diagnostica per immagini", "sara.conti@demo.local", "none"),
    ]
    doctors = []
    for name, specialty, email, provider in doctor_specs:
        d = db.query(Doctor).filter(Doctor.full_name == name).first()
        if not d:
            d = Doctor(full_name=name, specialty=specialty, email=email, phone="+39 02 5550 1000", active=True,
                       external_provider=provider, external_calendar_id="primary" if provider == "google" else None,
                       external_calendar_user=email if provider == "microsoft365" else None)
            db.add(d); db.flush()
        doctors.append(d)

    visit_specs = [
        ("CARD", "Visita cardiologica", 30, "#2563eb"),
        ("DERM", "Visita dermatologica", 30, "#7c3aed"),
        ("ECO", "Ecografia addome", 60, "#059669"),
        ("CTRL", "Visita di controllo", 30, "#ea580c"),
        ("URG", "Valutazione urgente", 30, "#dc2626"),
    ]
    visits = []
    for code, name, duration, color in visit_specs:
        v = db.query(VisitType).filter(VisitType.code == code).first()
        if not v:
            v = VisitType(code=code, name=name, duration_minutes=duration, buffer_before_minutes=0,
                          buffer_after_minutes=0, color=color, active=True, recall_enabled=True, recall_days=365 if code in {"CARD","DERM"} else 180 if code=="CTRL" else 90, followup_enabled=True)
            db.add(v); db.flush()
        demo_prices = {"CARD": 12000, "DERM": 10000, "ECO": 9000, "CTRL": 6500, "URG": 14000}
        v.private_price_cents = demo_prices.get(code, 8000)
        v.ssn_enabled = code in {"CARD", "DERM", "ECO", "CTRL"}
        v.ssn_ticket_cents = 3600 if v.ssn_enabled else 0
        v.requires_prescription = code in {"ECO", "URG"}
        visits.append(v)

    agendas = []
    for idx, doctor in enumerate(doctors):
        name = f"Agenda {doctor.specialty}"
        a = db.query(Agenda).filter(Agenda.name == name, Agenda.doctor_id == doctor.id).first()
        if not a:
            a = Agenda(name=name, doctor_id=doctor.id, location="Poliambulatorio Centro - Piano " + str(idx + 1),
                       timezone="Europe/Rome", slot_minutes=30, active=True)
            a.visit_types = visits if idx == 0 else ([visits[1], visits[3], visits[4]] if idx == 1 else [visits[2], visits[3]])
            db.add(a); db.flush()
            for weekday in range(5):
                db.add(AgendaRule(agenda_id=a.id, weekday=weekday, start_time=time(8, 0), end_time=time(13, 0), active=True))
                db.add(AgendaRule(agenda_id=a.id, weekday=weekday, start_time=time(14, 0), end_time=time(18, 30), active=True))
        agendas.append(a)
    db.flush()

    people = [
        ("Giulia Ferri", "giulia.ferri", "+39 333 410 2201", "FRRGLI82C51F205X", "1982-03-11"),
        ("Luca Romano", "luca.romano", "+39 333 410 2202", "RMNLCU74L12F205P", "1974-07-12"),
        ("Elena Greco", "elena.greco", "+39 333 410 2203", "GRC LNE90A41H501Z".replace(" ", ""), "1990-01-01"),
        ("Paolo Moretti", "paolo.moretti", "+39 333 410 2204", "MRTPLA65S20F205R", "1965-11-20"),
        ("Chiara Lombardi", "chiara.lombardi", "+39 333 410 2205", "LMBCHR88E66F205B", "1988-05-26"),
        ("Andrea Villa", "andrea.villa", "+39 333 410 2206", "VLLNDR79P15F205C", "1979-09-15"),
        ("Martina Costa", "martina.costa", "+39 333 410 2207", "CSTMRT93D54F205A", "1993-04-14"),
        ("Roberto Galli", "roberto.galli", "+39 333 410 2208", "GLLRRT58R10F205L", "1958-10-10"),
    ]
    patients = []
    for name, slug, phone, fiscal, dob in people:
        email = f"{DEMO_PREFIX}{slug}@example.test"
        u = User(email=email, hashed_password=hash_password("Demo123!"), full_name=name, role="patient", phone=phone, is_active=True)
        db.add(u); db.flush()
        p = Patient(user_id=u.id, date_of_birth=datetime.strptime(dob, "%Y-%m-%d").date(), fiscal_code=fiscal,
                    notes="Paziente demo - dati sintetici", reminder_enabled="true",
                    reminder_channels="sms,whatsapp,email")
        db.add(p); db.flush(); patients.append(p)

    # Appuntamenti distribuiti tra passato, oggi e prossimi giorni.
    specs = [
        (0, 9, 0, 0, 0, "confirmed", "normal"),
        (0, 10, 0, 1, 1, "confirmed", "normal"),
        (0, 11, 15, 2, 2, "pending", "urgent"),
        (0, 14, 30, 3, 0, "confirmed", "normal"),
        (0, 16, 0, 4, 1, "confirmed", "normal"),
        (1, 8, 45, 5, 0, "confirmed", "normal"),
        (1, 10, 30, 6, 2, "confirmed", "normal"),
        (1, 15, 0, 7, 3, "pending", "normal"),
        (2, 9, 30, 0, 4, "confirmed", "urgent"),
        (2, 11, 0, 1, 0, "confirmed", "normal"),
        (3, 14, 0, 2, 1, "confirmed", "normal"),
        (-1, 10, 0, 3, 3, "completed", "normal"),
        (-2, 15, 30, 4, 0, "cancelled", "normal"),
    ]
    bookings = []
    for day, hour, minute, pidx, vidx, status, priority in specs:
        vt = visits[vidx]
        doctor = doctors[0 if vidx in (0, 4) else (1 if vidx in (1, 3) else 2)]
        agenda = next((a for a in agendas if a.doctor_id == doctor.id), agendas[0])
        start = _at(day, hour, minute)
        b = Booking(patient_id=patients[pidx].id, service_name=vt.name, scheduled_at=start,
                    end_at=start + timedelta(minutes=vt.duration_minutes), agenda_id=agenda.id,
                    visit_type_id=vt.id, status=status, priority=priority,
                    notes="Demo: appuntamento generato automaticamente",
                    external_provider=doctor.external_provider if doctor.external_provider != "none" else None,
                    external_sync_status="synced" if doctor.external_provider != "none" and status != "cancelled" else "local")
        b.doctors = [doctor]
        db.add(b); db.flush(); bookings.append(b)

    # Pre-visita e check-in demo.
    ensure_default_templates(db)
    for idx, b in enumerate(bookings):
        tmpl = db.query(PreVisitTemplate).filter((PreVisitTemplate.visit_type_id == b.visit_type_id) | (PreVisitTemplate.visit_type_id == None)).first()
        if tmpl and b.status != "cancelled":
            completed = idx in {0, 3, 5, 8, 11}
            db.add(PreVisitSubmission(booking_id=b.id, template_id=tmpl.id, status="completed" if completed else "pending", answers_json=json.dumps({"reason":"Controllo periodico demo","allergies":"Nessuna nota"}, ensure_ascii=False) if completed else "{}", consent_accepted=completed, consent_name=b.patient.user.full_name if completed else None, consent_at=datetime.now() if completed else None, completed_at=datetime.now() if completed else None))
            cstatus = "not_arrived"
            if b.scheduled_at.date() == datetime.now().date():
                cstatus = "checked_in" if idx in {0, 2} else ("waiting" if idx == 1 else "not_arrived")
            db.add(BookingCheckIn(booking_id=b.id, status=cstatus, source="patient_link" if cstatus == "checked_in" else "operator", checked_in_at=datetime.now() if cstatus in {"checked_in","waiting"} else None, waiting_at=datetime.now() if cstatus == "waiting" else None))

    # Lista d'attesa demo: preferenze diverse per mostrare il matching automatico.
    wait_specs = [
        (patients[5], visits[0], agendas[0], 20, 8, 30, 12, 30),
        (patients[6], visits[0], agendas[0], 10, 9, 0, 18, 0),
        (patients[7], visits[3], agendas[1], 0, 14, 0, 18, 30),
    ]
    demo_wait_entries = []
    for patient, visit, agenda, priority, h1, m1, h2, m2 in wait_specs:
        w = WaitlistEntry(patient_id=patient.id, visit_type_id=visit.id, agenda_id=agenda.id, doctor_id=agenda.doctor_id,
            preferred_from=_at(0,0,0), preferred_to=_at(14,23,59), preferred_time_from=f"{h1:02d}:{m1:02d}", preferred_time_to=f"{h2:02d}:{m2:02d}",
            priority=priority, channels="sms,email", status="waiting", notes="Demo lista d'attesa automatica")
        db.add(w); db.flush(); demo_wait_entries.append(w)
    # Una proposta demo aperta rende visibile anche lo stato di offerta senza inviare messaggi reali.
    demo_slot = _at(4, 12, 0)
    demo_offer = WaitlistOffer(agenda_id=agendas[0].id, visit_type_id=visits[0].id, scheduled_at=demo_slot,
        end_at=demo_slot+timedelta(minutes=visits[0].duration_minutes), status="open", expires_at=datetime.now()+timedelta(minutes=20))
    db.add(demo_offer); db.flush()
    demo_wait_entries[0].status = "offered"
    db.add(WaitlistOfferRecipient(offer_id=demo_offer.id, waitlist_entry_id=demo_wait_entries[0].id, patient_id=demo_wait_entries[0].patient_id,
        token_id=uuid4().hex, channel="sms", target=patients[5].user.phone, status="offered", provider_response="Demo: proposta simulata", sent_at=datetime.now()))

    # Reminder dimostrativi: pending, sent e failed.
    reminder_samples = [
        (bookings[0], "sms", "sent", -2, "Consegnato"),
        (bookings[1], "whatsapp", "sent", -1, "WhatsApp accepted"),
        (bookings[2], "email", "failed", -1, "SMTP demo: mailbox non raggiungibile"),
        (bookings[5], "sms", "pending", 0, None),
        (bookings[6], "whatsapp", "pending", 1, None),
    ]
    for booking, channel, status, delta_h, provider_response in reminder_samples:
        target = booking.patient.user.phone if channel != "email" else booking.patient.user.email
        db.add(AppointmentReminder(booking_id=booking.id, kind="reminder", offset_hours=24, channel=channel,
                                   target=target, scheduled_for=datetime.now() + timedelta(hours=delta_h), status=status,
                                   message=f"Promemoria demo: {booking.service_name}", provider_response=provider_response,
                                   attempts=1 if status in {"sent", "failed"} else 0,
                                   sent_at=datetime.now() - timedelta(hours=1) if status == "sent" else None))

    # Journey multicanale dimostrativo telefono -> SMS -> web -> documenti -> handoff.
    sid_phone = str(uuid4())
    phone_ctx = {"journey_id": sid_phone, "owner": "llm", "origin_channel": "phone", "current_channel": "web",
                 "patient_name": patients[0].user.full_name, "demo": True}
    db.add(ChatSession(id=sid_phone, channel="phone", sender_id=patients[0].user.phone, status="handoff",
                       context_json=json.dumps(phone_ctx)))
    db.flush()
    db.add_all([
        ConversationChannel(session_id=sid_phone, channel="phone", external_id=patients[0].user.phone, display_name=patients[0].user.full_name),
        ConversationChannel(session_id=sid_phone, channel="web", external_id=f"demo-web-{sid_phone[:8]}", display_name="Link SMS"),
        ChatMessage(session_id=sid_phone, role="user", content="Vorrei parlare con un operatore per una visita cardiologica."),
        ChatMessage(session_id=sid_phone, role="assistant", content="Certo. Ti metto in contatto con un operatore e mantengo il contesto della conversazione."),
        HandoffEvent(session_id=sid_phone, event="requested", from_owner="llm", to_owner="operator", reason="Richiesta esplicita del paziente"),
    ])
    call = Call(caller_number=patients[0].user.phone, callee_number="800100200", channel="PJSIP/demo-0001", status="active", started_at=datetime.now() - timedelta(minutes=4))
    db.add(call); db.flush()
    db.add(OperatorHandoff(session_id=sid_phone, call_id=call.id, source="livekit", status="waiting_operator",
                           mode="ring_group", fallback_action="callback", reason="Richiesta operatore umano",
                           summary="Paziente interessato a visita cardiologica. Ha chiesto assistenza umana.",
                           requested_at=datetime.now() - timedelta(seconds=12), expires_at=datetime.now() + timedelta(seconds=45)))

    # Journey WhatsApp risolto dall'AI e Telegram con documenti, per popolare la dashboard.
    for channel, pidx, status in [("whatsapp", 5, "bot"), ("telegram", 6, "bot")]:
        sid = str(uuid4())
        ctx = {"journey_id": sid, "owner": "llm", "origin_channel": channel, "current_channel": channel, "demo": True}
        db.add(ChatSession(id=sid, channel=channel, sender_id=patients[pidx].user.phone, status=status, context_json=json.dumps(ctx)))
        db.flush()
        db.add(ConversationChannel(session_id=sid, channel=channel, external_id=f"demo-{channel}-{pidx}", display_name=patients[pidx].user.full_name))
        db.add(ChatMessage(session_id=sid, role="user", content="Quali documenti devo portare alla visita?"))
        db.add(ChatMessage(session_id=sid, role="assistant", content="Porta documento di identita, tessera sanitaria e referti precedenti pertinenti."))

    # Continuità di cura demo: follow-up da gestire e recall programmati.
    completed = [b for b in bookings if b.status == "completed"]
    for b in completed:
        if not db.query(PostVisitFollowup).filter(PostVisitFollowup.booking_id == b.id).first():
            db.add(PostVisitFollowup(booking_id=b.id, patient_id=b.patient_id, scheduled_for=datetime.now()-timedelta(hours=2), status="needs_contact", channel="sms", target=b.patient.user.phone, attempts=1, provider_response="Demo: risposta ricevuta", sent_at=datetime.now()-timedelta(hours=20), completed_at=datetime.now()-timedelta(hours=18), rating=3, wellbeing="same", needs_contact=True, comment="Vorrei chiarire la terapia prescritta.", token_id=uuid4().hex))
        if not db.query(RecallCampaign).filter(RecallCampaign.source_booking_id == b.id).first():
            db.add(RecallCampaign(source_booking_id=b.id, patient_id=b.patient_id, visit_type_id=b.visit_type_id, due_at=datetime.now()+timedelta(days=30), status="scheduled", token_id=uuid4().hex))
    # Un recall già scaduto e inviato per mostrare la coda operativa.
    src = bookings[0]
    if not db.query(RecallCampaign).filter(RecallCampaign.patient_id==src.patient_id, RecallCampaign.source_booking_id==None).first():
        db.add(RecallCampaign(source_booking_id=None, patient_id=src.patient_id, visit_type_id=src.visit_type_id, due_at=datetime.now()-timedelta(days=2), status="sent", channel="whatsapp", target=src.patient.user.phone, attempts=1, provider_response="Demo: consegnato", sent_at=datetime.now()-timedelta(days=1), token_id=uuid4().hex))

    analytics_created = 0  # legacy analytics seed disabled
    commerce_created = _ensure_commerce_demo(db, patients, bookings)
    db.commit()
    return {
        "ok": True, "created": True,
        "patients": len(patients), "doctors": len(doctors), "visit_types": len(visits),
        "agendas": len(agendas), "bookings": len(bookings), "waitlist": 3, "previsit": len([b for b in bookings if b.status != "cancelled"]), "journeys": 3,
        "followups": 1, "recalls": 2, "analytics_history": analytics_created, "commerce": commerce_created, "message": "Dataset demo CUP creato"
    }
