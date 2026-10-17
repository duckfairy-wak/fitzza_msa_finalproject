from typing import Literal, Optional

from pydantic import BaseModel, Field


class RecommendationCreateRequest(BaseModel):
    query: str = Field(..., description="사용자의 자연어 패션 추천 질의")


class RecommendationAcceptedResponse(BaseModel):
    requestId: int = Field(..., description="생성된 추천 요청 ID")
    status: Literal["PROCESSING", "DONE", "FAILED"] = Field(
        default="PROCESSING",
        description="추천 요청 처리 상태",
    )


class RecommendedProductItem(BaseModel):
    productId: int
    productName: str
    brandName: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    price: int
    imageUrl: Optional[str] = None
    color: Optional[str] = None
    size: Optional[str] = None
    fitPercent: Optional[float] = None
    evidence: Optional[str] = None


class RecommendedComboItem(BaseModel):
    comboId: int
    items: list[RecommendedProductItem] = Field(default_factory=list)
    totalPrice: int
    passStatus: str
    harmonyScore: float
    feedbackSummary: str
    budgetExceeded: bool = False


class RecommendationDetailResponse(BaseModel):
    requestId: int
    status: Literal["PROCESSING", "DONE", "FAILED"]
    searchType: Optional[str] = None
    tpoSummary: Optional[str] = None
    items: list[RecommendedProductItem] = Field(default_factory=list)
    combos: list[RecommendedComboItem] = Field(default_factory=list)
    message: Optional[str] = None


class RecommendationHistoryItem(BaseModel):
    requestId: int
    queryText: str
    tpoSummary: Optional[str] = None
    createdAt: str


class RecommendationHistoryPageResponse(BaseModel):
    content: list[RecommendationHistoryItem] = Field(default_factory=list)
    page: int
    totalPages: int


class InternalComboProductItem(BaseModel):
    productId: int
    productName: str
    price: int
    imageUrl: Optional[str] = None


class InternalComboResponse(BaseModel):
    owned: bool
    items: list[InternalComboProductItem] = Field(default_factory=list)
    totalPrice: Optional[int] = None
    feedbackSummary: Optional[str] = None


class SizeFeedbackRequest(BaseModel):
    userId: int = Field(..., gt=0)
    productId: int = Field(..., gt=0)
    optionId: int = Field(..., gt=0)
    sizeFeedback: Literal["SMALL", "FIT", "BIG"]
