from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class Call(Base):
    __tablename__ = "calls"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"))

    caller_number = Column(String(50))
    callee_number = Column(String(50))
    channel = Column(String(100))

    # Correlazione Asterisk: tutti i canali della stessa telefonata
    # condividono lo stesso Linkedid.
    asterisk_linkedid = Column(String(100), nullable=True, index=True)

    # OMNIA_VOICE_CALL_V1
    asterisk_uniqueid = Column(String(100), nullable=True, index=True)

    source = Column(
        String(30),
        nullable=False,
        default="asterisk",
    )

    direction = Column(
        String(20),
        nullable=False,
        default="inbound",
    )

    # unknown | operator | voice_ai
    call_type = Column(
        String(30),
        nullable=False,
        default="unknown",
    )

    operator_extension = Column(String(30))
    answered_at = Column(DateTime)

    patient_id = Column(
        Integer,
        ForeignKey("patients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status = Column(
        String(20),
        nullable=False,
        default="ringing",
    )  # ringing|active|held|ended|missed

    started_at = Column(DateTime, server_default=func.now())
    ended_at = Column(DateTime)
    duration_seconds = Column(Integer)

    ai_intent = Column(String(60))
    ai_sentiment = Column(String(30))
    ai_confidence = Column(Integer)  # 0..100
    ai_last_summary = Column(Text)

    booking = relationship("Booking", back_populates="calls")
