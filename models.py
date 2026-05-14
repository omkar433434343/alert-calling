from sqlalchemy import Column, String, Text, Boolean, DateTime, Float
from sqlalchemy.dialects.postgresql import JSON
from database import Base
from datetime import datetime
import uuid


class TriageRecord(Base):
    __tablename__ = "triage_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(String, nullable=True)
    patient_name = Column(String, nullable=True)
    caller_phone = Column(String, nullable=True)
    call_sid = Column(String, nullable=True)

    source = Column(String, nullable=True)
    
    transcript = Column(Text, nullable=True)

    symptoms = Column(JSON, nullable=True)

    severity = Column(String, nullable=True)
    sickle_cell_risk = Column(Boolean, nullable=True)

    brief = Column(Text, nullable=True)
    reviewed = Column(Boolean, default=False)

    district = Column(String, nullable=True)
    user_id = Column(String, nullable=True)
    
    asha_worker_id = Column(String, nullable=True)
    longitude = Column(Float, nullable=True)
    latitude = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)