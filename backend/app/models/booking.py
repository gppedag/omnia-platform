from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    service_name = Column(String(255), nullable=False)
    scheduled_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime)
    agenda_id = Column(Integer, ForeignKey("agendas.id", ondelete="SET NULL"))
    visit_type_id = Column(Integer, ForeignKey("visit_types.id", ondelete="SET NULL"))
    external_provider = Column(String(30))
    external_event_id = Column(String(512))
    external_sync_status = Column(String(255))
    status = Column(String(20), nullable=False, default="pending")  # pending|confirmed|cancelled|completed
    priority = Column(String(10), nullable=False, default="normal")  # normal|urgent
    notes = Column(Text)
    care_regime = Column(String(20), nullable=False, default='private')
    quoted_price_cents = Column(Integer, nullable=False, default=0)
    hold_expires_at = Column(DateTime)
    source = Column(String(40), nullable=False, default='operator')
    created_at = Column(DateTime, server_default=func.now())

    patient = relationship("Patient", back_populates="bookings")
    calls = relationship("Call", back_populates="booking")
    doctors = relationship("Doctor", secondary="booking_doctors", back_populates="bookings")
    agenda = relationship("Agenda")
    visit_type = relationship("VisitType")
