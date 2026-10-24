"""vton-service 요청 및 응답 Pydantic 스키마."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from pydantic import BaseModel, Field, model_validator


class FittingItemInput(BaseModel):
    productId: int = Field(
        description="피팅할 상품 ID",
        json_schema_extra={"example": 101},
    )
    imageUrl: str | None = Field(
        default=None,
        description="추천된 특정 색상의 상품 이미지 URL (제공 시 기본 썸네일 대신 피팅 합성 입력으로 사용)",
        json_schema_extra={"example": "https://image.msscdn.net/images/goods_img/green.jpg"},
    )


class FittingCreateRequest(BaseModel):
    requestId: int | None = Field(
        default=None,
        description="추천 요청 ID (추천 대화 연동용)",
        json_schema_extra={"example": 6},
    )
    photoId: int | None = Field(
        default=None,
        description="사용자 전신 사진 ID (현재 미구현 시 기본 아바타로 피팅 진행)",
        json_schema_extra={"example": 1},
    )
    productIds: list[int] | None = Field(
        default=None,
        min_length=1,
        max_length=5,
        description="피팅할 상품 ID 목록 (최소 1개, 최대 5개)",
        json_schema_extra={"example": [101, 201]},
    )
    items: list[FittingItemInput] | None = Field(
        default=None,
        min_length=1,
        max_length=5,
        description="피팅할 상품 및 추천 색상별 이미지 목록 (productIds 대신 사용 권장)",
        json_schema_extra={
            "example": [
                {"productId": 101, "imageUrl": "https://image.msscdn.net/images/goods_img/green.jpg"},
                {"productId": 201, "imageUrl": "https://image.msscdn.net/images/goods_img/black.jpg"},
            ]
        },
    )

    @model_validator(mode="before")
    @classmethod
    def validate_items_and_product_ids(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        raw_items = data.get("items")
        raw_pids = data.get("productIds")

        if not raw_items and not raw_pids:
            raise ValueError("productIds 또는 items 중 하나는 반드시 입력해야 합니다.")

        # items가 제공된 경우 productIds를 자동으로 도출하여 하위 호환성 유지
        if raw_items and isinstance(raw_items, list):
            extracted_pids = []
            for item in raw_items:
                if isinstance(item, dict) and "productId" in item:
                    try:
                        extracted_pids.append(int(item["productId"]))
                    except (ValueError, TypeError):
                        pass
                elif hasattr(item, "productId"):
                    extracted_pids.append(int(getattr(item, "productId")))
            if not raw_pids and extracted_pids:
                data["productIds"] = extracted_pids

        return data


class FittingCreateResponse(BaseModel):
    fittingId: int = Field(
        description="생성된 가상 피팅 작업 ID",
        json_schema_extra={"example": 1},
    )
    status: Literal["PENDING"] = Field(
        default="PENDING",
        description="작업 상태 (비동기 처리 시작)",
        json_schema_extra={"example": "PENDING"},
    )


class FittingProductResponse(BaseModel):
    productId: int = Field(
        description="상품 ID",
        json_schema_extra={"example": 101},
    )
    productName: str = Field(
        description="상품명",
        json_schema_extra={"example": "베이직 오버핏 반팔 티셔츠"},
    )
    price: int = Field(
        description="상품 가격(원)",
        json_schema_extra={"example": 29000},
    )
    imageUrl: str = Field(
        description="상품 썸네일 이미지 URL",
        json_schema_extra={"example": "https://cdn.example.com/item.png"},
    )
    categoryName: str = Field(
        description="의류 카테고리 (상의, 하의, 아우터, 신발, 모자)",
        json_schema_extra={"example": "상의"},
    )


class FittingDetailResponse(BaseModel):
    fittingId: int = Field(
        description="가상 피팅 작업 ID",
        json_schema_extra={"example": 1},
    )
    userId: int = Field(
        description="피팅 요청 사용자 ID",
        json_schema_extra={"example": 7},
    )
    requestId: int | None = Field(
        default=None,
        description="가상 피팅을 요청했던 추천 대화의 requestId",
        json_schema_extra={"example": 6},
    )
    userImageUrl: str | None = Field(
        default=None,
        description="사용자 원본 얼굴/전신 사진 URL (요청 시 업로드한 경우)",
        json_schema_extra={"example": "http://api.fitzza.com/api/vton/1/user-image"},
    )
    status: Literal["PENDING", "COMPLETED", "FAILED"] = Field(
        description="피팅 진행 상태 (PENDING, COMPLETED, FAILED)",
        json_schema_extra={"example": "COMPLETED"},
    )
    resultImageUrl: str | None = Field(
        default=None,
        description="피팅 완성 이미지 URL (COMPLETED 상태일 때 유효)",
        json_schema_extra={"example": "http://api.fitzza.com/api/vton/1/image"},
    )
    errorMessage: str | None = Field(
        default=None,
        description="피팅 실패 시 상세 에러 메시지",
    )
    products: list[FittingProductResponse] = Field(
        default_factory=list,
        description="피팅에 사용된 상품 목록",
    )
    createdAt: str = Field(
        description="생성 일시 (ISO-8601)",
        json_schema_extra={"example": "2026-10-18T17:30:00+00:00"},
    )
    updatedAt: str = Field(
        description="수정 일시 (ISO-8601)",
        json_schema_extra={"example": "2026-10-18T17:31:00+00:00"},
    )


class FittingSummaryResponse(BaseModel):
    fittingId: int = Field(
        description="가상 피팅 고유 ID",
        json_schema_extra={"example": 1},
    )
    userId: int = Field(
        description="피팅 요청 사용자 ID",
        json_schema_extra={"example": 7},
    )
    requestId: int | None = Field(
        default=None,
        description="가상 피팅을 요청했던 추천 대화의 requestId",
        json_schema_extra={"example": 6},
    )
    status: Literal["PENDING", "COMPLETED", "FAILED"] = Field(
        description="피팅 진행 상태",
        json_schema_extra={"example": "COMPLETED"},
    )
    resultImageUrl: str | None = Field(
        default=None,
        description="피팅 완성 이미지 URL",
        json_schema_extra={"example": "http://api.fitzza.com/api/vton/1/image"},
    )
    userImageUrl: str | None = Field(
        default=None,
        description="피팅에 사용된 사용자 얼굴 이미지 URL",
        json_schema_extra={"example": "http://api.fitzza.com/api/vton/1/user-image"},
    )
    productCount: int = Field(
        default=0,
        description="착용한 상품 개수",
        json_schema_extra={"example": 3},
    )
    products: list[FittingProductResponse] = Field(
        default_factory=list,
        description="착용 상품 목록 요약",
    )
    createdAt: str = Field(
        description="생성 일시 (ISO-8601)",
        json_schema_extra={"example": "2026-10-20T10:00:00Z"},
    )


class FittingListResponse(BaseModel):
    items: list[FittingSummaryResponse] = Field(
        default_factory=list,
        description="사용자 가상 피팅 목록",
    )
    totalCount: int = Field(
        default=0,
        description="전체 피팅 건수",
        json_schema_extra={"example": 5},
    )


class InternalResultProduct(BaseModel):
    productId: int = Field(
        description="상품 ID",
        json_schema_extra={"example": 1},
    )
    productName: str = Field(
        description="상품명",
        json_schema_extra={"example": "셔츠"},
    )
    price: int = Field(
        description="가격",
        json_schema_extra={"example": 39000},
    )
    imageUrl: str = Field(
        description="상품 이미지 URL",
        json_schema_extra={"example": "https://cdn.example.com/1.png"},
    )


class InternalFittingResponse(BaseModel):
    owned: bool = Field(
        description="요청한 사용자의 피팅인지 여부",
        json_schema_extra={"example": True},
    )
    status: str = Field(
        description="피팅 상태 (COMPLETED, PENDING, FAILED)",
        json_schema_extra={"example": "COMPLETED"},
    )
    resultImageUrl: str | None = Field(
        default=None,
        description="완성된 이미지 URL (status가 COMPLETED일 때만 유효)",
        json_schema_extra={"example": "http://api.fitzza.com/api/vton/1/image"},
    )
    products: list[InternalResultProduct] = Field(
        default_factory=list,
        description="피팅에 사용된 상품 정보 목록 (community-service 호환용)",
    )


class ErrorResponse(BaseModel):
    status: int = Field(
        description="HTTP 상태 코드",
        json_schema_extra={"example": 400},
    )
    code: str = Field(
        description="오류 식별 코드",
        json_schema_extra={"example": "INVALID_REQUEST"},
    )
    message: str = Field(
        description="오류 상세 안내 메시지",
        json_schema_extra={"example": "요청 값이 올바르지 않습니다."},
    )


