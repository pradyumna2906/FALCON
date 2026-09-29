"""Strict owner workspace reports, notifications and privacy contracts."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class WorkspaceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ReauthenticationRequest(WorkspaceSchema):
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]


class ErasureRequest(ReauthenticationRequest):
    confirmation: Literal["DELETE MY ACCOUNT"]


class NotificationPreferences(WorkspaceSchema):
    in_app_enabled: bool = True


class NotificationResponse(WorkspaceSchema):
    id: UUID
    title: str
    detail: str
    created_at: datetime
    read_at: datetime | None


class NotificationList(WorkspaceSchema):
    items: tuple[NotificationResponse, ...]
    has_more: bool


class SessionResponse(WorkspaceSchema):
    id: UUID
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime
    current: bool


class SessionList(WorkspaceSchema):
    items: tuple[SessionResponse, ...]
    has_more: bool
