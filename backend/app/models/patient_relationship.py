from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey,
    Integer, String, Text, func
)
from sqlalchemy.orm import relationship

from app.db.database import Base


class PatientRelationship(Base):
    __tablename__ = "patient_relationships"

    id = Column(Integer, primary_key=True, index=True)

    # Paziente beneficiario.
    patient_id = Column(
        Integer,
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Se il delegato possiede gia' un account CUP.
    related_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    relationship_type = Column(
        String(30),
        nullable=False,
        default="other",
    )

    display_name = Column(String(255))
    phone = Column(String(80), index=True)
    email = Column(String(255))

    can_book = Column(Boolean, nullable=False, default=False)
    can_manage_bookings = Column(Boolean, nullable=False, default=False)
    can_receive_reminders = Column(Boolean, nullable=False, default=False)
    can_receive_document_requests = Column(Boolean, nullable=False, default=False)
    can_send_documents = Column(Boolean, nullable=False, default=False)

    authorization_type = Column(
        String(30),
        nullable=False,
        default="informal",
    )
    authorization_verified_at = Column(DateTime)
    authorization_notes = Column(Text)

    is_primary = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    patient = relationship(
        "Patient",
        foreign_keys=[patient_id],
    )

    related_user = relationship(
        "User",
        foreign_keys=[related_user_id],
    )
