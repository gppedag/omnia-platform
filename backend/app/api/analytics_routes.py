from datetime import datetime, timedelta, time
import json
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db.database import get_db
from app.models.booking import Booking
from app.models.calendar import Agenda, AgendaRule, AgendaException
from app.models.chat import ChatSession
from app.models.handoff import OperatorHandoff
from app.models.reminder import AppointmentReminder, BookingReminderResponse
from app.models.previsit import BookingCheckIn, PreVisitSubmission
from app.models.waitlist import WaitlistEntry, WaitlistOffer, WaitlistOfferRecipient
from app.models.care import PostVisitFollowup, RecallCampaign
from app.models.user import User

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _window(days: int):
    days = max(1, min(int(days or 30), 365))
    end = datetime.now()
    start = end - timedelta(days=days)
    return days, start, end


def _pct(num, den):
    return round((num / den * 100.0), 1) if den else 0.0


def _duration_minutes(booking: Booking):
    if booking.end_at and booking.scheduled_at:
        return max(1, int((booking.end_at - booking.scheduled_at).total_seconds() / 60))
    if booking.visit_type and booking.visit_type.duration_minutes:
        return max(1, int(booking.visit_type.duration_minutes))
    return 30


def _basic_metrics(db: Session, start: datetime, end: datetime):
    bookings = db.query(Booking).filter(Booking.scheduled_at >= start, Booking.scheduled_at < end).all()
    status = Counter((b.status or "unknown") for b in bookings)
    booking_ids = [b.id for b in bookings]

    checkins = []
    if booking_ids:
        checkins = db.query(BookingCheckIn).filter(BookingCheckIn.booking_id.in_(booking_ids)).all()
    checkin_by_booking = {c.booking_id: c for c in checkins}
    no_show = sum(1 for b in bookings if checkin_by_booking.get(b.id) and checkin_by_booking[b.id].status == "no_show")
    attended = sum(1 for b in bookings if checkin_by_booking.get(b.id) and checkin_by_booking[b.id].status in {"checked_in", "waiting", "in_visit", "completed"})
    eligible_attendance = attended + no_show

    reminder_rows = db.query(AppointmentReminder).filter(AppointmentReminder.created_at >= start, AppointmentReminder.created_at < end).all()
    rem_status = Counter(r.status or "unknown" for r in reminder_rows)
    sent_or_failed = rem_status["sent"] + rem_status["failed"]

    handoffs = db.query(OperatorHandoff).filter(OperatorHandoff.requested_at >= start, OperatorHandoff.requested_at < end).all()
    accepted = [h for h in handoffs if h.accepted_at]
    response_secs = [max(0.0, (h.accepted_at - h.requested_at).total_seconds()) for h in accepted if h.requested_at]

    followups = db.query(PostVisitFollowup).filter(PostVisitFollowup.created_at >= start, PostVisitFollowup.created_at < end).all()
    recalls = db.query(RecallCampaign).filter(RecallCampaign.created_at >= start, RecallCampaign.created_at < end).all()

    previsit_rows = []
    if booking_ids:
        previsit_rows = db.query(PreVisitSubmission).filter(PreVisitSubmission.booking_id.in_(booking_ids)).all()
    previsit_completed = sum(1 for x in previsit_rows if x.status == "completed")

    responses = []
    if booking_ids:
        responses = db.query(BookingReminderResponse).filter(BookingReminderResponse.booking_id.in_(booking_ids)).all()
    response_actions = Counter(x.action for x in responses)

    return {
        "bookings": {
            "total": len(bookings),
            "confirmed": status["confirmed"],
            "pending": status["pending"],
            "completed": status["completed"],
            "cancelled": status["cancelled"],
            "no_show": no_show,
            "attendance_rate": _pct(attended, eligible_attendance),
            "no_show_rate": _pct(no_show, eligible_attendance),
            "confirmation_rate": _pct(status["confirmed"] + status["completed"], max(1, len(bookings) - status["cancelled"])),
            "confirmed_from_reminder": response_actions["confirmed"],
            "cancelled_from_reminder": response_actions["cancelled"],
        },
        "reminders": {
            "total": len(reminder_rows),
            "sent": rem_status["sent"],
            "failed": rem_status["failed"],
            "pending": rem_status["pending"],
            "delivery_rate": _pct(rem_status["sent"], sent_or_failed),
        },
        "handoffs": {
            "requested": len(handoffs),
            "accepted": len(accepted),
            "acceptance_rate": _pct(len(accepted), len(handoffs)),
            "avg_response_seconds": round(sum(response_secs) / len(response_secs), 1) if response_secs else 0.0,
        },
        "previsit": {
            "total": len(previsit_rows),
            "completed": previsit_completed,
            "completion_rate": _pct(previsit_completed, len(previsit_rows)),
        },
        "care": {
            "followups_total": len(followups),
            "followups_needs_contact": sum(1 for x in followups if x.status == "needs_contact" or x.needs_contact),
            "followups_completed": sum(1 for x in followups if x.status == "completed"),
            "recalls_total": len(recalls),
            "recalls_booked": sum(1 for x in recalls if x.status == "booked"),
            "recall_conversion_rate": _pct(sum(1 for x in recalls if x.status == "booked"), sum(1 for x in recalls if x.status in {"sent", "booked", "completed"})),
        },
    }


@router.get("/overview")
def overview(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db), user=Depends(require_role("admin", "operator"))):
    days, start, end = _window(days)
    m = _basic_metrics(db, start, end)
    waiting_handoffs = db.query(OperatorHandoff).filter(OperatorHandoff.status.in_(["waiting_operator", "ringing"])).count()
    waiting_list = db.query(WaitlistEntry).filter(WaitlistEntry.status.in_(["waiting", "offered"])).count()
    failed_reminders = db.query(AppointmentReminder).filter(AppointmentReminder.status == "failed").count()
    m.update({
        "period": {"days": days, "start": start, "end": end},
        "attention": {
            "handoffs_waiting": waiting_handoffs,
            "waitlist_open": waiting_list,
            "reminders_failed": failed_reminders,
            "followups_needs_contact": m["care"]["followups_needs_contact"],
        },
    })
    return m


def _capacity_minutes(db: Session, agenda: Agenda, start: datetime, end: datetime):
    rules = db.query(AgendaRule).filter(AgendaRule.agenda_id == agenda.id, AgendaRule.active == True).all()
    exceptions = db.query(AgendaException).filter(AgendaException.agenda_id == agenda.id, AgendaException.date >= start.date(), AgendaException.date <= end.date()).all()
    ex_by_day = defaultdict(list)
    for ex in exceptions:
        ex_by_day[ex.date].append(ex)

    total = 0
    cur = start.date()
    last = end.date()
    while cur <= last:
        for rule in rules:
            if rule.weekday != cur.weekday():
                continue
            if rule.valid_from and cur < rule.valid_from:
                continue
            if rule.valid_to and cur > rule.valid_to:
                continue
            mins = max(0, int((datetime.combine(cur, rule.end_time) - datetime.combine(cur, rule.start_time)).total_seconds() / 60))
            total += mins
        for ex in ex_by_day.get(cur, []):
            if ex.start_time and ex.end_time:
                mins = max(0, int((datetime.combine(cur, ex.end_time) - datetime.combine(cur, ex.start_time)).total_seconds() / 60))
            else:
                # giornata intera: usa la capacita' ordinaria della giornata gia calcolata
                mins = sum(max(0, int((datetime.combine(cur, r.end_time) - datetime.combine(cur, r.start_time)).total_seconds() / 60)) for r in rules if r.weekday == cur.weekday())
            if ex.kind == "blocked":
                total -= mins
            elif ex.kind == "open":
                total += mins
        cur += timedelta(days=1)
    return max(0, total)


@router.get("/admin")
def admin_analytics(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db), user=Depends(require_role("admin"))):
    days, start, end = _window(days)
    base = _basic_metrics(db, start, end)

    # Saturazione agende
    agendas = db.query(Agenda).filter(Agenda.active == True).all()
    period_bookings = db.query(Booking).filter(Booking.scheduled_at >= start, Booking.scheduled_at < end, Booking.status != "cancelled").all()
    booked_by_agenda = defaultdict(int)
    for b in period_bookings:
        if b.agenda_id:
            booked_by_agenda[b.agenda_id] += _duration_minutes(b)
    agenda_rows = []
    total_capacity = 0
    total_booked = 0
    for agenda in agendas:
        capacity = _capacity_minutes(db, agenda, start, end)
        booked = booked_by_agenda.get(agenda.id, 0)
        total_capacity += capacity
        total_booked += booked
        agenda_rows.append({
            "agenda_id": agenda.id,
            "name": agenda.name,
            "doctor": agenda.doctor.full_name if agenda.doctor else None,
            "location": agenda.location,
            "capacity_minutes": capacity,
            "booked_minutes": booked,
            "occupancy_rate": _pct(booked, capacity),
        })
    agenda_rows.sort(key=lambda x: x["occupancy_rate"], reverse=True)

    # Canali e conversione chatbot -> prenotazione. Il booking_id viene salvato nel context_json dal flusso guidato.
    sessions = db.query(ChatSession).filter(ChatSession.created_at >= start, ChatSession.created_at < end).all()
    channel_totals = Counter()
    channel_converted = Counter()
    converted = 0
    for s in sessions:
        ch = s.channel or "unknown"
        channel_totals[ch] += 1
        try:
            ctx = json.loads(s.context_json or "{}")
        except Exception:
            ctx = {}
        if ctx.get("booking_id"):
            converted += 1
            channel_converted[ch] += 1
    channel_rows = []
    for ch, count in channel_totals.most_common():
        channel_rows.append({"channel": ch, "sessions": count, "bookings": channel_converted[ch], "conversion_rate": _pct(channel_converted[ch], count)})

    # Performance operatori su handoff + prenotazioni create.
    handoffs = db.query(OperatorHandoff).filter(OperatorHandoff.requested_at >= start, OperatorHandoff.requested_at < end).all()
    users = {u.id: u for u in db.query(User).filter(User.role.in_(["admin", "operator"])).all()}
    op = defaultdict(lambda: {"accepted": 0, "response": [], "bookings": 0})
    for h in handoffs:
        if h.operator_id:
            op[h.operator_id]["accepted"] += 1
            if h.accepted_at and h.requested_at:
                op[h.operator_id]["response"].append(max(0.0, (h.accepted_at - h.requested_at).total_seconds()))
    creator_rows = db.query(Booking).filter(Booking.created_at >= start, Booking.created_at < end, Booking.operator_id.isnot(None)).all()
    for b in creator_rows:
        op[b.operator_id]["bookings"] += 1
    operator_rows = []
    for uid, vals in op.items():
        resp = vals["response"]
        operator_rows.append({
            "operator_id": uid,
            "name": users.get(uid).full_name if users.get(uid) else f"Operatore {uid}",
            "handoffs_accepted": vals["accepted"],
            "avg_response_seconds": round(sum(resp) / len(resp), 1) if resp else 0.0,
            "bookings_created": vals["bookings"],
        })
    operator_rows.sort(key=lambda x: (x["handoffs_accepted"] + x["bookings_created"]), reverse=True)

    # Waitlist efficiency
    offers = db.query(WaitlistOffer).filter(WaitlistOffer.created_at >= start, WaitlistOffer.created_at < end).all()
    offer_ids = [x.id for x in offers]
    recipients = db.query(WaitlistOfferRecipient).filter(WaitlistOfferRecipient.offer_id.in_(offer_ids)).all() if offer_ids else []
    booked_offers = sum(1 for x in offers if x.status == "booked")
    accepted_recipients = sum(1 for x in recipients if x.status == "accepted")

    # Trend giornaliero appuntamenti / no-show
    booking_by_day = defaultdict(lambda: {"bookings": 0, "cancelled": 0, "completed": 0, "no_show": 0})
    checkins = db.query(BookingCheckIn).filter(BookingCheckIn.booking_id.in_([b.id for b in period_bookings])).all() if period_bookings else []
    ci = {x.booking_id: x for x in checkins}
    all_period = db.query(Booking).filter(Booking.scheduled_at >= start, Booking.scheduled_at < end).all()
    for b in all_period:
        key = b.scheduled_at.date().isoformat()
        booking_by_day[key]["bookings"] += 1
        if b.status == "cancelled": booking_by_day[key]["cancelled"] += 1
        if b.status == "completed": booking_by_day[key]["completed"] += 1
        if ci.get(b.id) and ci[b.id].status == "no_show": booking_by_day[key]["no_show"] += 1
    trend = [{"date": d, **vals} for d, vals in sorted(booking_by_day.items())]

    return {
        "period": {"days": days, "start": start, "end": end},
        **base,
        "occupancy": {"overall_rate": _pct(total_booked, total_capacity), "capacity_minutes": total_capacity, "booked_minutes": total_booked, "agendas": agenda_rows},
        "channels": {"sessions": len(sessions), "converted_bookings": converted, "conversion_rate": _pct(converted, len(sessions)), "items": channel_rows},
        "operators": operator_rows,
        "waitlist": {"offers": len(offers), "booked_offers": booked_offers, "fill_rate": _pct(booked_offers, len(offers)), "recipients": len(recipients), "accepted_recipients": accepted_recipients},
        "trend": trend,
    }
