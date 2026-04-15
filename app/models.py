from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


StatusType = Literal["在校", "不在校"]
RunOutcome = Literal["success", "skipped", "failed"]
TriggerType = Literal["manual", "scheduler"]


def _normalize_text(value: str) -> str:
    return value.strip()


def _validate_schedule_time(value: str) -> str:
    clean_value = value.strip()
    parts = clean_value.split(":")
    if len(parts) != 2:
        raise ValueError("时间格式必须是 HH:MM")
    hour_text, minute_text = parts
    if not hour_text.isdigit() or not minute_text.isdigit():
        raise ValueError("时间格式必须是 HH:MM")
    hour = int(hour_text)
    minute = int(minute_text)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("时间超出合法范围")
    return f"{hour:02d}:{minute:02d}"


class UserBase(BaseModel):
    label: str = Field(default="", max_length=64)
    student_no: str = Field(min_length=4, max_length=64)
    desired_status: StatusType = "在校"
    off_campus_city: str = Field(default="", max_length=128)
    off_campus_district: str = Field(default="", max_length=128)
    off_campus_reason: str = Field(default="", max_length=128)
    schedule_time: str = Field(default="07:30")
    overwrite_existing: bool = False
    enabled: bool = True

    @field_validator(
        "label",
        "student_no",
        "off_campus_city",
        "off_campus_district",
        "off_campus_reason",
        mode="before",
    )
    @classmethod
    def _strip_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return _normalize_text(str(value))

    @field_validator("schedule_time")
    @classmethod
    def _schedule_time(cls, value: str) -> str:
        return _validate_schedule_time(value)

    @model_validator(mode="after")
    def _validate_off_campus_fields(self) -> "UserBase":
        if self.desired_status == "不在校":
            if not self.off_campus_city:
                raise ValueError("选择不在校时必须填写省/市/区")
            if not self.off_campus_district:
                raise ValueError("选择不在校时必须填写详细地址")
            if not self.off_campus_reason:
                raise ValueError("选择不在校时必须填写事由")
        return self


class UserCreate(UserBase):
    password: str = Field(min_length=1, max_length=256)

    @field_validator("password", mode="before")
    @classmethod
    def _strip_password(cls, value: Any) -> str:
        if value is None:
            raise ValueError("密码不能为空")
        return _normalize_text(str(value))


class UserUpdate(UserBase):
    password: str | None = Field(default=None, max_length=256)

    @field_validator("password", mode="before")
    @classmethod
    def _strip_optional_password(cls, value: Any) -> str | None:
        if value is None:
            return None
        stripped = _normalize_text(str(value))
        return stripped or None


class UserResponse(UserBase):
    id: int
    created_at: str
    updated_at: str
    has_password: bool = True


class RunResponse(BaseModel):
    id: int
    user_id: int
    user_label: str
    student_no: str
    run_date: str
    triggered_by: TriggerType
    outcome: RunOutcome
    message: str
    desired_payload: dict[str, Any]
    remote_snapshot: dict[str, Any]
    created_at: str


class HealthResponse(BaseModel):
    status: str
    user_count: int
    timezone: str
    base_url: str


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)

    @field_validator("password", mode="before")
    @classmethod
    def _strip_password(cls, value: Any) -> str:
        if value is None:
            raise ValueError("密码不能为空")
        return _normalize_text(str(value))


class SessionResponse(BaseModel):
    authenticated: bool


@dataclass(slots=True)
class UserRecord:
    id: int
    label: str
    student_no: str
    password_ciphertext: str
    desired_status: str
    off_campus_city: str
    off_campus_district: str
    off_campus_reason: str
    schedule_time: str
    overwrite_existing: bool
    enabled: bool
    created_at: str
    updated_at: str


@dataclass(slots=True)
class RunRecord:
    id: int
    user_id: int
    user_label: str
    student_no: str
    run_date: str
    triggered_by: str
    outcome: str
    message: str
    desired_payload: dict[str, Any]
    remote_snapshot: dict[str, Any]
    created_at: str
