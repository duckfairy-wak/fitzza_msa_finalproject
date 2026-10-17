from typing import Literal

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    code: str
    message: str


class HealthResponse(BaseModel):
    status: Literal["UP", "NOT_READY"]
    liveness: Literal["UP"] = "UP"
    readiness: Literal["UP", "DOWN"]
