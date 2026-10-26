"""Operational health response schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Safe liveness response without dependency or configuration details."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"
    service: Literal["falcon-api"] = "falcon-api"


class ReadinessResponse(BaseModel):
    """Safe readiness response without dependency or configuration details."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ready"] = "ready"
    service: Literal["falcon-api"] = "falcon-api"
