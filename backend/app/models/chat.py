from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, BigInteger, func
from sqlalchemy.orm import relationship
from app.db.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True)
    channel = Column(String(32), nullable=False, default="web")
    sender_id = Column(String(255))
    # journey_id identifica lo stesso percorso omnicanale; patient_id viene valorizzato quando il paziente e riconoscibile.
    journey_id = Column(String(36), nullable=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="bot")  # bot|handoff|closed
    context_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )
    attachments = relationship(
        "ChatAttachment",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatAttachment.created_at",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user|assistant|operator|system
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")


class ChatAttachment(Base):
    __tablename__ = "chat_attachments"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False, unique=True)
    mime_type = Column(String(120), nullable=False, default="application/octet-stream")
    size_bytes = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())

    session = relationship("ChatSession", back_populates="attachments")
