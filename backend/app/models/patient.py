from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    date_of_birth = Column(Date)
    fiscal_code = Column(String(32))
    notes = Column(Text)
    reminder_enabled = Column(String(10), nullable=False, default="true")
    reminder_channels = Column(String(120))
    reminder_telegram_chat_id = Column(String(120))
    created_at = Column(DateTime, server_default=func.now())

    # Livello di verifica dell'identita del paziente
    identity_status = Column(
        String(30),
        nullable=False,
        default="self_declared",
    )

    user = relationship("User", back_populates="patient_profile")
    bookings = relationship("Booking", back_populates="patient")
