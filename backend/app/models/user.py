from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)

    # Anagrafica strutturata.
    # full_name resta per retrocompatibilita' con i moduli esistenti.
    first_name = Column(String(120))
    last_name = Column(String(160))

    role = Column(String(20), nullable=False, default="patient")  # admin | operator | patient
    phone = Column(String(50))

    # OMNIA_OPERATOR_VOIP_V1
    voip_extension = Column(String(30))
    voip_password_enc = Column(String)
    is_active = Column(Boolean, default=True)
    can_chat = Column(Boolean, nullable=False, default=True)
    can_phone = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now())

    # Patient digital identity
    phone_verified = Column(Boolean, nullable=False, default=False)
    email_verified = Column(Boolean, nullable=False, default=False)
    account_status = Column(String(20), nullable=False, default="active")
    activation_source = Column(String(20))
    last_login_at = Column(DateTime)

    patient_profile = relationship("Patient", back_populates="user", uselist=False)
