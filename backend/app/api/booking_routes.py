from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.booking import Booking
from app.schemas import BookingCreate, BookingUpdate, BookingOut
from app.auth import get_current_user, require_role
from app.services.reminder_service import ensure_booking_reminders, rebuild_future_reminders, cancel_future_reminders
from app.services.waitlist_service import create_offer_for_cancelled_booking
from app.services.previsit_service import ensure_previsit_for_booking

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


@router.get("/", response_model=List[BookingOut])
def list_bookings(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(Booking)
    if date_from:
        q = q.filter(Booking.scheduled_at >= date_from)
    if date_to:
        q = q.filter(Booking.scheduled_at <= date_to)
    if status_filter:
        q = q.filter(Booking.status == status_filter)
    return q.order_by(Booking.scheduled_at).all()


@router.post("/", response_model=BookingOut, status_code=201)
def create_booking(payload: BookingCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    booking = Booking(**payload.model_dump())
    db.add(booking)
    db.commit()
    db.refresh(booking)
    db.refresh(booking, attribute_names=["patient"])
    ensure_booking_reminders(db, booking, include_confirmation=True)
    ensure_previsit_for_booking(db, booking)
    return booking


@router.patch("/{booking_id}", response_model=BookingOut)
def update_booking(booking_id: int, payload: BookingUpdate, db: Session = Depends(get_db),
                    user=Depends(require_role("admin", "operator"))):
    booking = db.query(Booking).get(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Prenotazione non trovata")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(booking, field, value)
    db.commit()
    db.refresh(booking)
    if booking.status == "cancelled":
        cancel_future_reminders(db, booking.id)
        create_offer_for_cancelled_booking(db, booking)
    else:
        rebuild_future_reminders(db, booking)
        ensure_previsit_for_booking(db, booking)
        if booking.status == "completed":
            from app.services.care_service import ensure_care_for_completed_booking
            ensure_care_for_completed_booking(db, booking)
    return booking


@router.delete("/{booking_id}", status_code=204)
def cancel_booking(booking_id: int, db: Session = Depends(get_db),
                    user=Depends(require_role("admin", "operator"))):
    booking = db.query(Booking).get(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Prenotazione non trovata")
    booking.status = "cancelled"
    db.commit()
    cancel_future_reminders(db, booking.id)
    create_offer_for_cancelled_booking(db, booking)
