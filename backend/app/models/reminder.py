from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class AppointmentReminder(Base):
    __tablename__ = "appointment_reminders"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(30), nullable=False, default="reminder")  # confirmation|reminder|manual
    offset_hours = Column(Integer, nullable=False, default=0)
    channel = Column(String(30), nullable=False)  # sms|whatsapp|email|telegram
    target = Column(String(255))
    scheduled_for = Column(DateTime, nullable=False, index=True)
    status = Column(String(30), nullable=False, default="pending")  # pending|sent|failed|skipped|cancelled
    message = Column(Text)
    provider_response = Column(Text)
    attempts = Column(Integer, nullable=False, default=0)
    sent_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    booking = relationship("Booking")


class BookingReminderResponse(Base):
    __tablename__ = "booking_reminder_responses"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(30), nullable=False)  # confirmed|cancelled
    source = Column(String(30), nullable=False, default="reminder_link")
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, server_default=func.now())
