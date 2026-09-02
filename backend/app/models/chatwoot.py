from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base


class ChatwootBinding(Base):
    __tablename__ = "chatwoot_bindings"
    __table_args__ = (UniqueConstraint("conversation_id", name="uq_chatwoot_conversation"),)

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    contact_id = Column(Integer, nullable=True)
    contact_source_id = Column(String(255), nullable=True)
    inbox_identifier = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, default="open")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    session = relationship("ChatSession")
