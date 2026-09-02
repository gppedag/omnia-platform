from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class WaitlistEntry(Base):
    __tablename__ = 'waitlist_entries'
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey('patients.id', ondelete='CASCADE'), nullable=False, index=True)
    visit_type_id = Column(Integer, ForeignKey('visit_types.id', ondelete='SET NULL'), index=True)
    agenda_id = Column(Integer, ForeignKey('agendas.id', ondelete='SET NULL'), index=True)
    doctor_id = Column(Integer, ForeignKey('doctors.id', ondelete='SET NULL'), index=True)
    preferred_from = Column(DateTime)
    preferred_to = Column(DateTime)
    preferred_time_from = Column(String(5))
    preferred_time_to = Column(String(5))
    priority = Column(Integer, nullable=False, default=0)
    channels = Column(String(120))
    status = Column(String(20), nullable=False, default='waiting')  # waiting|offered|booked|paused|cancelled
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    patient = relationship('Patient')
    visit_type = relationship('VisitType')
    agenda = relationship('Agenda')
    doctor = relationship('Doctor')


class WaitlistOffer(Base):
    __tablename__ = 'waitlist_offers'
    id = Column(Integer, primary_key=True)
    source_booking_id = Column(Integer, ForeignKey('bookings.id', ondelete='SET NULL'))
    agenda_id = Column(Integer, ForeignKey('agendas.id', ondelete='SET NULL'), nullable=False)
    visit_type_id = Column(Integer, ForeignKey('visit_types.id', ondelete='SET NULL'))
    scheduled_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default='open')  # open|booked|expired|cancelled
    accepted_patient_id = Column(Integer, ForeignKey('patients.id', ondelete='SET NULL'))
    accepted_booking_id = Column(Integer, ForeignKey('bookings.id', ondelete='SET NULL'))
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    agenda = relationship('Agenda')
    visit_type = relationship('VisitType')
    recipients = relationship('WaitlistOfferRecipient', back_populates='offer', cascade='all, delete-orphan')


class WaitlistOfferRecipient(Base):
    __tablename__ = 'waitlist_offer_recipients'
    id = Column(Integer, primary_key=True)
    offer_id = Column(Integer, ForeignKey('waitlist_offers.id', ondelete='CASCADE'), nullable=False, index=True)
    waitlist_entry_id = Column(Integer, ForeignKey('waitlist_entries.id', ondelete='CASCADE'), nullable=False)
    patient_id = Column(Integer, ForeignKey('patients.id', ondelete='CASCADE'), nullable=False)
    token_id = Column(String(64), unique=True, nullable=False, index=True)
    channel = Column(String(20))
    target = Column(String(255))
    status = Column(String(20), nullable=False, default='offered')  # offered|accepted|expired|failed|declined
    provider_response = Column(Text)
    sent_at = Column(DateTime)
    responded_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    offer = relationship('WaitlistOffer', back_populates='recipients')
    entry = relationship('WaitlistEntry')
    patient = relationship('Patient')
