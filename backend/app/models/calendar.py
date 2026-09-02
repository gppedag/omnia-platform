from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Time, ForeignKey, Table, Text, func
from sqlalchemy.orm import relationship
from app.db.database import Base

agenda_visit_types = Table(
    'agenda_visit_types', Base.metadata,
    Column('agenda_id', Integer, ForeignKey('agendas.id', ondelete='CASCADE'), primary_key=True),
    Column('visit_type_id', Integer, ForeignKey('visit_types.id', ondelete='CASCADE'), primary_key=True),
)

booking_doctors = Table(
    'booking_doctors', Base.metadata,
    Column('booking_id', Integer, ForeignKey('bookings.id', ondelete='CASCADE'), primary_key=True),
    Column('doctor_id', Integer, ForeignKey('doctors.id', ondelete='CASCADE'), primary_key=True),
)

class Doctor(Base):
    __tablename__ = 'doctors'
    id = Column(Integer, primary_key=True)
    color_hex = Column(String(7), nullable=True)
    full_name = Column(String(255), nullable=False)
    specialty = Column(String(255))
    email = Column(String(255))
    phone = Column(String(80))
    active = Column(Boolean, nullable=False, default=True)
    external_provider = Column(String(20), nullable=False, default='none')  # none|google|microsoft365
    external_calendar_id = Column(String(512))
    external_calendar_user = Column(String(255))
    created_at = Column(DateTime, server_default=func.now())
    agendas = relationship('Agenda', back_populates='doctor', cascade='all, delete-orphan')
    bookings = relationship('Booking', secondary=booking_doctors, back_populates='doctors')

class VisitType(Base):
    __tablename__ = 'visit_types'
    id = Column(Integer, primary_key=True)
    color_hex = Column(String(7), nullable=True)
    code = Column(String(80), unique=True, index=True)
    name = Column(String(255), nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=60)
    buffer_before_minutes = Column(Integer, nullable=False, default=0)
    buffer_after_minutes = Column(Integer, nullable=False, default=0)
    color = Column(String(20), nullable=False, default='#0d6efd')
    active = Column(Boolean, nullable=False, default=True)
    notes = Column(Text)
    recall_enabled = Column(Boolean, nullable=False, default=True)
    recall_days = Column(Integer)
    followup_enabled = Column(Boolean, nullable=False, default=True)
    private_price_cents = Column(Integer, nullable=False, default=0)
    ssn_enabled = Column(Boolean, nullable=False, default=False)
    ssn_ticket_cents = Column(Integer, nullable=False, default=0)
    requires_prescription = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())
    agendas = relationship('Agenda', secondary=agenda_visit_types, back_populates='visit_types')

class Agenda(Base):
    __tablename__ = 'agendas'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    doctor_id = Column(Integer, ForeignKey('doctors.id', ondelete='CASCADE'), nullable=False)
    location = Column(String(255))
    timezone = Column(String(80), nullable=False, default='Europe/Rome')
    slot_minutes = Column(Integer, nullable=False, default=60)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())
    doctor = relationship('Doctor', back_populates='agendas')
    visit_types = relationship('VisitType', secondary=agenda_visit_types, back_populates='agendas')
    rules = relationship('AgendaRule', back_populates='agenda', cascade='all, delete-orphan')
    exceptions = relationship('AgendaException', back_populates='agenda', cascade='all, delete-orphan')

class AgendaRule(Base):
    __tablename__ = 'agenda_rules'
    id = Column(Integer, primary_key=True)
    agenda_id = Column(Integer, ForeignKey('agendas.id', ondelete='CASCADE'), nullable=False)
    weekday = Column(Integer, nullable=False)  # 0=lunedi
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    valid_from = Column(Date)
    valid_to = Column(Date)
    active = Column(Boolean, nullable=False, default=True)
    agenda = relationship('Agenda', back_populates='rules')

class AgendaException(Base):
    __tablename__ = 'agenda_exceptions'
    id = Column(Integer, primary_key=True)
    agenda_id = Column(Integer, ForeignKey('agendas.id', ondelete='CASCADE'), nullable=False)
    date = Column(Date, nullable=False)
    start_time = Column(Time)
    end_time = Column(Time)
    kind = Column(String(20), nullable=False, default='blocked')  # blocked|open
    note = Column(String(255))
    agenda = relationship('Agenda', back_populates='exceptions')
