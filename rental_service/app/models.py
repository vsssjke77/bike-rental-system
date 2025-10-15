from sqlalchemy import Column, Integer, DateTime, String, Float, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Rental(Base):
    __tablename__ = "rentals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    bike_id = Column(Integer, index=True)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    actual_end_time = Column(DateTime, nullable=True)
    total_price = Column(Float)
    status = Column(String, default="active")  # active, completed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)