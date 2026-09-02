from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base


class ConversationChannel(Base):
    __tablename__ = "conversation_channels"
    __table_args__ = (UniqueConstraint("channel", "external_id", name="uq_channel_external"),)

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(32), nullable=False, index=True)  # web|whatsapp|telegram|phone
    external_id = Column(String(255), nullable=False, index=True)
    display_name = Column(String(255))
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    session = relationship("ChatSession")


class HandoffEvent(Base):
    __tablename__ = "handoff_events"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    event = Column(String(40), nullable=False)  # requested|ringing|accepted|returned_to_llm|closed|failed
    from_owner = Column(String(20), nullable=False, default="llm")
    to_owner = Column(String(20), nullable=False, default="operator")
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    reason = Column(Text)
    call_id = Column(Integer, ForeignKey("calls.id", ondelete="SET NULL"))
    created_at = Column(DateTime, server_default=func.now())
