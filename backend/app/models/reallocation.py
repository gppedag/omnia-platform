from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Time,
    ForeignKey, func
)
from sqlalchemy.orm import relationship

from app.db.database import Base


class ServiceInterruption(Base):
    __tablename__ = "service_interruptions"

    id = Column(Integer, primary_key=True)

    agenda_id = Column(
        Integer,
        ForeignKey("agendas.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    scope_type = Column(
        String(30),
        nullable=False,
        default="agenda",
    )

    specialty = Column(String(255))
    facility_wide = Column(String(10), default="false")

    kind = Column(
        String(30),
        nullable=False,
        default="technical_fault",
    )  # technical_fault | maintenance

    title = Column(String(255), nullable=False)
    note = Column(Text)

    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    start_time = Column(Time)
    end_time = Column(Time)

    status = Column(
        String(30),
        nullable=False,
        default="active",
    )  # draft | active | resolved

    created_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    created_at = Column(DateTime, server_default=func.now())
    resolved_at = Column(DateTime)

    agenda = relationship("Agenda")


class ReallocationCase(Base):
    __tablename__ = "reallocation_cases"

    id = Column(Integer, primary_key=True)

    interruption_id = Column(
        Integer,
        ForeignKey(
            "service_interruptions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    booking_id = Column(
        Integer,
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    original_agenda_id = Column(Integer)
    original_scheduled_at = Column(DateTime)
    original_end_at = Column(DateTime)

    proposed_agenda_id = Column(
        Integer,
        ForeignKey("agendas.id", ondelete="SET NULL"),
    )

    proposed_scheduled_at = Column(DateTime)
    proposed_end_at = Column(DateTime)

    action = Column(
        String(30),
        nullable=False,
        default="reallocate",
    )  # reallocate | cancel

    status = Column(
        String(40),
        nullable=False,
        default="pending",
    )
    # pending
    # proposal_ready
    # approved
    # notified
    # accepted
    # rejected
    # contact_requested
    # reallocated
    # cancel_requested
    # cancel_confirmed

    token_id = Column(
        String(80),
        unique=True,
        index=True,
    )

    notified_at = Column(DateTime)
    responded_at = Column(DateTime)
    completed_at = Column(DateTime)

    operator_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    note = Column(Text)

    confirmation_source = Column(String(40))
    confirmed_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    confirmed_at = Column(DateTime)
    confirmation_note = Column(Text)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    interruption = relationship("ServiceInterruption")
    booking = relationship("Booking")
    proposed_agenda = relationship(
        "Agenda",
        foreign_keys=[proposed_agenda_id],
    )



class ServiceInterruptionAgenda(Base):
    __tablename__ = "service_interruption_agendas"

    id = Column(Integer, primary_key=True)

    interruption_id = Column(
        Integer,
        ForeignKey(
            "service_interruptions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    agenda_id = Column(
        Integer,
        ForeignKey(
            "agendas.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    interruption = relationship(
        "ServiceInterruption"
    )

    agenda = relationship(
        "Agenda"
    )
