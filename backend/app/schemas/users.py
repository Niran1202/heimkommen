from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime


class SavedTripIn(BaseModel):
    label: str | None = Field(default=None, max_length=80)
    from_station_id: str
    to_station_id: str
    usual_departure: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    regional_only: bool = True


class SavedTripOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str | None
    from_station_id: str
    from_station_name: str
    to_station_id: str
    to_station_name: str
    usual_departure: str | None
    regional_only: bool
    created_at: datetime
