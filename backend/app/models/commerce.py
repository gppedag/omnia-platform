from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, BigInteger, func
from app.db.database import Base


class PaymentRequest(Base):
    __tablename__ = "payment_requests"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    description = Column(String(255), nullable=False)
    amount_cents = Column(BigInteger, nullable=False)
    currency = Column(String(8), nullable=False, default="EUR")
    provider = Column(String(40), nullable=False, default="manual")
    status = Column(String(30), nullable=False, default="pending")  # pending|sent|paid|cancelled|expired|failed
    checkout_url = Column(Text)
    external_reference = Column(String(255), index=True)
    channels = Column(String(120))
    provider_response = Column(Text)
    due_at = Column(DateTime)
    sent_at = Column(DateTime)
    paid_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SignatureRequest(Base):
    __tablename__ = "signature_requests"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False)
    message = Column(Text)
    original_filename = Column(String(255), nullable=False)
    stored_path = Column(Text, nullable=False)
    document_sha256 = Column(String(64), nullable=False)
    status = Column(String(30), nullable=False, default="pending")  # pending|sent|viewed|signed|declined|expired|failed
    channels = Column(String(120))
    signer_name = Column(String(255))
    signature_png_path = Column(Text)
    signature_sha256 = Column(String(64))
    signed_ip = Column(String(120))
    signed_user_agent = Column(Text)
    declined_reason = Column(Text)
    sent_at = Column(DateTime)
    viewed_at = Column(DateTime)
    signed_at = Column(DateTime)
    declined_at = Column(DateTime)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
