from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, func
from app.db.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    channel = Column(String(20), nullable=False)  # email|sms|push
    message = Column(Text, nullable=False)
    sent = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
