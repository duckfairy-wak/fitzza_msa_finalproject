from datetime import datetime, timezone
from uuid import UUID

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Fitzza Recommendation Service", version="0.1.0")


class RecommendationRequest(BaseModel):
    user_id: UUID
    limit: int = Field(default=10, ge=1, le=100)


class RecommendationResponse(BaseModel):
    user_id: UUID
    product_ids: list[UUID]


@app.get("/api/v1/recommendations/status")
def service_status() -> dict[str, str]:
    return {
        "service": "recommendation-service",
        "status": "UP",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/v1/recommendations", response_model=RecommendationResponse)
def recommend(request: RecommendationRequest) -> RecommendationResponse:
    """Recommendation contract placeholder; connect Qdrant and model inference next."""
    return RecommendationResponse(user_id=request.user_id, product_ids=[])
