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
    recommendedSize: Optional[str] = None
    availableSizes: Optional[list[str]] = None
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
    queryText: str = ""
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
    size: int = 20
    totalElements: int = 0
    totalPages: int
    hasNext: bool = False


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


class VisualSearchResultItem(BaseModel):
    productId: int = Field(..., description="상품 고유 식별자")
    productName: str = Field(..., description="상품명")
    brandName: Optional[str] = Field(None, description="브랜드명")
    category: Optional[str] = Field(None, description="대분류 카테고리 (상의, 아우터, 하의 등)")
    subcategory: Optional[str] = Field(None, description="중분류/소분류 카테고리")
    price: int = Field(..., description="상품 가격 (원)")
    imageUrl: Optional[str] = Field(None, description="상품 대표 이미지 URL")
    color: Optional[str] = Field(None, description="대표 색상")
    similarityScore: float = Field(..., description="Fashion-CLIP 시각적 유사도 점수 (0.0 ~ 1.0)")
    productUrl: Optional[str] = Field(None, description="상품 상세 페이지 URL")


class VisualSearchResponse(BaseModel):
    detectedCategory: Optional[str] = Field(None, description="AI가 이미지에서 자동 감지한 상위 카테고리 (상의, 아우터, 하의, 신발, 모자)")
    detectedColor: Optional[str] = Field(None, description="AI가 이미지에서 자동 감지한 대표 색상 (black, white, navy 등)")
    items: list[VisualSearchResultItem] = Field(default_factory=list, description="유사도 순 정렬된 상품 목록")
    totalCount: int = Field(..., description="검색된 유사 상품 총 개수")


class PersonalizedProductItem(BaseModel):
    productId: int = Field(..., description="상품 ID", json_schema_extra={"example": 1024})
    productName: str = Field(..., description="상품명", json_schema_extra={"example": "베이직 오버핏 맨투맨"})
    brandName: Optional[str] = Field(None, description="브랜드명", json_schema_extra={"example": "무신사 스탠다드"})
    price: int = Field(..., description="판매가 (원)", json_schema_extra={"example": 39900})
    thumbnailUrl: Optional[str] = Field(None, description="대표 이미지 URL", json_schema_extra={"example": "https://image.msscdn.net/images/goods_img/..."})
    status: Optional[str] = Field(default="ON_SALE", description="판매 상태 (ON_SALE, OUT_OF_STOCK)", json_schema_extra={"example": "ON_SALE"})
    category: Optional[str] = Field(None, description="대분류 카테고리 (상의, 하의, 아우터, 신발, 모자)", json_schema_extra={"example": "상의"})
    wished: Optional[bool] = Field(None, description="요청 사용자의 찜 여부", json_schema_extra={"example": True})


class PersonalizedPageResponse(BaseModel):
    content: list[PersonalizedProductItem] = Field(default_factory=list, description="현재 페이지 추천 상품 목록")
    page: int = Field(..., ge=0, description="현재 페이지 번호 (0부터 시작)", json_schema_extra={"example": 0})
    size: int = Field(..., gt=0, description="페이지 크기", json_schema_extra={"example": 20})
    totalElements: int = Field(..., ge=0, description="전체 추천 후보 상품 수", json_schema_extra={"example": 80})
    totalPages: int = Field(..., ge=0, description="전체 페이지 수", json_schema_extra={"example": 4})
    hasNext: bool = Field(..., description="다음 페이지 존재 여부", json_schema_extra={"example": True})


class ProductSizeRecommendationResponse(BaseModel):
    recommendedSize: Optional[str] = Field(
        None,
        description="추천 사이즈 (예: S, M, L, 270). 추천 불가 시 null",
        json_schema_extra={"example": "L"},
    )
    fitPercent: Optional[float] = Field(
        None,
        ge=0.0,
        le=100.0,
        description="사이즈 적합도 퍼센트 (0.0 ~ 100.0). 추천 불가 시 null",
        json_schema_extra={"example": 92.0},
    )
    evidence: Optional[str] = Field(
        None,
        description="사용자에게 노출할 추천 근거 또는 안내 문구",
        json_schema_extra={"example": "유사 체형 사용자의 실측 데이터를 기준으로 추천된 사이즈입니다."},
    )


