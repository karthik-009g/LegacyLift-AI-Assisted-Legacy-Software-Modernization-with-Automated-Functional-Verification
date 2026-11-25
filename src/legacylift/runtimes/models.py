"""Typed, language-neutral observations and explicit runtime boundaries."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class RuntimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str = Field(min_length=1, max_length=2048)
    actor: Literal["anonymous", "alice", "outsider"] = "anonymous"
    json_body: JsonValue = None
    fixture_epoch: int | None = Field(default=None, ge=1768478400, le=1768564800)

    @field_validator("path")
    @classmethod
    def local_path_only(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value.startswith("//")
            or any(ord(char) < 32 for char in value)
        ):
            raise ValueError("request must use a local absolute path without control characters")
        return value


class RuntimeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: int = Field(ge=100, le=599)
    headers: dict[str, str]
    json_body: JsonValue = Field(default=None, alias="json")
    body_bytes: int = Field(ge=0)


class RuntimeAdapter(Protocol):
    """Controllers consume observations, not imported application objects."""

    def start(self) -> None: ...

    def request(self, request: RuntimeRequest) -> RuntimeResponse: ...

    def snapshot(self) -> dict[str, JsonValue]: ...

    def stop(self) -> None: ...
