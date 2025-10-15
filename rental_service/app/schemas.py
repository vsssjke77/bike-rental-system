from pydantic import BaseModel, validator
from datetime import datetime, timezone
from typing import Optional


class RentalBase(BaseModel):
    user_id: int
    bike_id: int
    start_time: datetime
    end_time: datetime

    @validator('start_time', 'end_time')
    def ensure_naive_datetime(cls, v):
        # Убеждаемся, что datetime без часового пояса
        if v.tzinfo is not None:
            # Преобразуем в UTC и удаляем информацию о часовом поясе
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


class RentalCreate(RentalBase):
    pass


class Rental(RentalBase):
    id: int
    total_price: float
    status: str
    actual_end_time: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True