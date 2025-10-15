from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class BikeBase(BaseModel):
    name: str
    description: str
    price_per_hour: float
    is_available: bool = True

class BikeCreate(BikeBase):
    pass

class BikeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price_per_hour: Optional[float] = None
    is_available: Optional[bool] = None

class Bike(BikeBase):
    id: int
    image_url: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True