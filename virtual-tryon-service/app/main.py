from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, status
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="Fitzza Virtual Try-On Service", version="0.1.0")


class TryOnRequest(BaseModel):
    user_id: UUID
    person_image_url: HttpUrl
    product_image_url: HttpUrl


class TryOnJob(BaseModel):
    job_id: UUID
    state: Literal["QUEUED"] = "QUEUED"


@app.get("/api/v1/tryon/status")
def service_status() -> dict[str, str]:
    return {
        "service": "virtual-tryon-service",
        "status": "UP",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/v1/tryon/jobs", response_model=TryOnJob, status_code=status.HTTP_202_ACCEPTED)
def create_job(_: TryOnRequest) -> TryOnJob:
    """Queue contract placeholder; connect SQS and the image worker next."""
    return TryOnJob(job_id=uuid4())
