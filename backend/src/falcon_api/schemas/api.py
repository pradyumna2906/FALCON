"""API discovery response schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApiIndexResponse(BaseModel):
    """Stable metadata returned by the API v1 index."""

    model_config = ConfigDict(frozen=True)

    service: Literal["falcon-api"] = "falcon-api"
    api_version: Literal["v1"] = "v1"
