from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class PostVisitFollowup(Base):
    __tablename__ = "post_visit_followups"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    scheduled_for = Column(DateTime, nullable=False, index=True)
    status = Column(String(24), nullable=False, default="scheduled")  # scheduled|sent|completed|needs_contact|failed|skipped
    channel = Column(String(24))
    target = Column(String(255))
    attempts = Column(Integer, nullable=False, default=0)
    provider_response = Column(Text)
    sent_at = Column(DateTime)
    completed_at = Column(DateTime)
    rating = Column(Integer)
    wellbeing = Column(String(32))  # better|same|worse
    needs_contact = Column(Boolean, nullable=False, default=False)
    comment = Column(Text)
    token_id = Column(String(64), unique=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    booking = relationship("Booking")
    patient = relationship("Patient")


class RecallCampaign(Base):
    __tablename__ = "recall_campaigns"

    id = Column(Integer, primary_key=True, index=True)
    source_booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"), unique=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    visit_type_id = Column(Integer, ForeignKey("visit_types.id", ondelete="SET NULL"), index=True)
    due_at = Column(DateTime, nullable=False, index=True)
    status = Column(String(24), nullable=False, default="scheduled")  # scheduled|due|sent|booked|completed|snoozed|failed|cancelled
    channel = Column(String(24))
    target = Column(String(255))
    attempts = Column(Integer, nullable=False, default=0)
    provider_response = Column(Text)
    sent_at = Column(DateTime)
    booked_booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"))
    snoozed_until = Column(DateTime)
    token_id = Column(String(64), unique=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    source_booking = relationship("Booking", foreign_keys=[source_booking_id])
    booked_booking = relationship("Booking", foreign_keys=[booked_booking_id])
    patient = relationship("Patient")
