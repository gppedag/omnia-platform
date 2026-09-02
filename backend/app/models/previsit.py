from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class PreVisitTemplate(Base):
    __tablename__ = "previsit_templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    visit_type_id = Column(Integer, ForeignKey("visit_types.id", ondelete="SET NULL"), index=True)
    form_json = Column(Text, nullable=False, default="[]")
    consent_title = Column(String(255), nullable=False, default="Consenso informato e privacy")
    consent_text = Column(Text, nullable=False, default="Dichiaro di aver letto le informazioni fornite e acconsento al trattamento dei dati per la gestione della prestazione.")
    required = Column(Boolean, nullable=False, default=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())

    visit_type = relationship("VisitType")


class PreVisitSubmission(Base):
    __tablename__ = "previsit_submissions"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    template_id = Column(Integer, ForeignKey("previsit_templates.id", ondelete="SET NULL"), index=True)
    status = Column(String(30), nullable=False, default="pending")  # pending|completed|waived
    answers_json = Column(Text, nullable=False, default="{}")
    consent_accepted = Column(Boolean, nullable=False, default=False)
    consent_name = Column(String(255))
    consent_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    booking = relationship("Booking")
    template = relationship("PreVisitTemplate")


class BookingCheckIn(Base):
    __tablename__ = "booking_checkins"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    status = Column(String(30), nullable=False, default="not_arrived")  # not_arrived|checked_in|waiting|in_visit|completed|no_show
    source = Column(String(30), nullable=False, default="operator")  # operator|patient_link|qr
    checked_in_at = Column(DateTime)
    waiting_at = Column(DateTime)
    in_visit_at = Column(DateTime)
    completed_at = Column(DateTime)
    notes = Column(Text)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    booking = relationship("Booking")
