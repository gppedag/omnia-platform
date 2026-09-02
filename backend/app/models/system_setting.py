from sqlalchemy import Column, String, Text, DateTime, func
from app.db.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(120), primary_key=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
