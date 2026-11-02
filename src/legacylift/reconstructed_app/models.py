"""Pydantic request and response models for the reconstructed service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, StrictStr, field_validator


class SessionStartRequest(BaseModel):
    user_id: StrictStr

    @field_validator("user_id")
    @classmethod
    def normalize_user_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 64:
            raise ValueError("user_id must contain 1 to 64 characters")
        return normalized


class TicketCreateRequest(BaseModel):
    subject: StrictStr
    description: StrictStr = ""

    @field_validator("subject")
    @classmethod
    def normalize_subject(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("subject must not be empty")
        if len(normalized) > 120:
            raise ValueError("subject must be at most 120 characters")
        return normalized

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        if len(value) > 2_000:
            raise ValueError("description must be at most 2000 characters")
        return value.strip()


class TicketStatusRequest(BaseModel):
    status: Literal["open", "in_progress", "closed"]


class SessionStartResponse(BaseModel):
    user_id: str


class TicketResponse(BaseModel):
    id: int
    subject: str
    description: str
    status: Literal["open", "in_progress", "closed"]
