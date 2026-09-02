from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, func
from app.db.database import Base


class AILearningSample(Base):
    __tablename__ = "ai_learning_samples"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(20), nullable=False, default="chat")  # chat|voice
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="SET NULL"), index=True)
    call_id = Column(Integer, ForeignKey("calls.id", ondelete="SET NULL"), index=True)
    operator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    consent_obtained = Column(Boolean, nullable=False, default=False)
    user_text = Column(Text, nullable=False)
    operator_text = Column(Text, nullable=False)
    anonymized_user_text = Column(Text, nullable=False)
    anonymized_operator_text = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending|approved|rejected
    review_notes = Column(Text)
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
