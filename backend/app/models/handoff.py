from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func, UniqueConstraint
from app.db.database import Base


class OperatorHandoff(Base):
    __tablename__ = "operator_handoffs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    call_id = Column(Integer, ForeignKey("calls.id", ondelete="SET NULL"), index=True)
    source = Column(String(32), nullable=False, default="chat")  # livekit|phone|web|whatsapp|telegram|chat
    status = Column(String(32), nullable=False, default="waiting_operator", index=True)
    mode = Column(String(24), nullable=False, default="manual")
    fallback_action = Column(String(24), nullable=False, default="callback")
    reason = Column(Text)
    summary = Column(Text)
    requested_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime)
    ringing_at = Column(DateTime)
    accepted_at = Column(DateTime)
    resolved_at = Column(DateTime)
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    rejected_by = Column(Text, nullable=False, default="")


class OperatorPresence(Base):
    __tablename__ = "operator_presence"
    __table_args__ = (UniqueConstraint("user_id", name="uq_operator_presence_user"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="available")  # available|busy|offline
    extension = Column(String(50))
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
