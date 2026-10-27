from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    created_at: datetime


class AuthResponse(BaseModel):
    user: UserRead
    csrf_token: str


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class ProfileUpdateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class NotificationRead(BaseModel):
    id: str
    event_type: str
    title: str
    message: str
    created_at: datetime
    read_at: datetime | None
    dataset_id: str | None
    finding_id: str | None
    operation_id: str | None


class AuditEventRead(BaseModel):
    id: str
    event_type: str
    outcome: str
    details: dict | None
    created_at: datetime
    dataset_id: str | None
    finding_id: str | None
    operation_id: str | None
