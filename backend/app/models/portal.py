from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class PatientPortalSession(Base):
    __tablename__ = "patient_portal_sessions"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(96), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    patient = relationship("Patient")


class PatientDocument(Base):
    __tablename__ = "patient_documents"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"))
    category = Column(String(30), nullable=False, default="document")  # report|booking|invoice|form|document
    title = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    stored_path = Column(String(1024), nullable=False)
    mime_type = Column(String(120), nullable=False, default="application/pdf")
    status = Column(String(30), nullable=False, default="available")
    created_at = Column(DateTime, server_default=func.now())
    patient = relationship("Patient")
    booking = relationship("Booking")


class QueueTicket(Base):
    __tablename__ = "queue_tickets"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"))
    code = Column(String(32), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="waiting")  # waiting|called|completed|cancelled
    estimated_wait_minutes = Column(Integer, nullable=False, default=15)
    checked_in_at = Column(DateTime, nullable=False, default=func.now())
    called_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    patient = relationship("Patient")
    booking = relationship("Booking")


class PortalSupportRequest(Base):
    __tablename__ = "portal_support_requests"
    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"))
    phone = Column(String(80))
    fiscal_code = Column(String(32))
    message = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="open")
    created_at = Column(DateTime, server_default=func.now())


class PatientDocumentShare(Base):
    __tablename__ = "patient_document_shares"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("patient_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(96), unique=True, nullable=False, index=True)
    access_code = Column(String(12), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    document = relationship("PatientDocument")
