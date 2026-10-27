import pytest
from pydantic import ValidationError

from app.schemas.recommendation import (
    PersonalizedProductItem,
    PersonalizedPageResponse,
)


def test_personalized_product_item_valid():
    item = PersonalizedProductItem(
        productId=101,
        productName="오버핏 니트",
        brandName="무신사 스탠다드",
        price=45000,
        thumbnailUrl="https://image.msscdn.net/sample.jpg",
        category="상의",
        wished=True,
    )
    assert item.productId == 101
    assert item.productName == "오버핏 니트"
    assert item.brandName == "무신사 스탠다드"
    assert item.price == 45000
    assert item.status == "ON_SALE"
    assert item.category == "상의"
    assert item.wished is True

    dumped = item.model_dump()
    assert dumped["productId"] == 101
    assert dumped["status"] == "ON_SALE"


def test_personalized_product_item_required_fields():
    with pytest.raises(ValidationError):
        # productId, productName, price are required
        PersonalizedProductItem(productId=101)


def test_personalized_page_response_valid():
    item1 = PersonalizedProductItem(
        productId=1,
        productName="반팔 티셔츠",
        price=19000,
        category="상의",
    )
    item2 = PersonalizedProductItem(
        productId=2,
        productName="슬랙스",
        price=35000,
        category="하의",
    )

    page_resp = PersonalizedPageResponse(
        content=[item1, item2],
        page=0,
        size=20,
        totalElements=80,
        totalPages=4,
        hasNext=True,
    )

    assert len(page_resp.content) == 2
    assert page_resp.page == 0
    assert page_resp.size == 20
    assert page_resp.totalElements == 80
    assert page_resp.totalPages == 4
    assert page_resp.hasNext is True


def test_personalized_page_response_constraints():
    # page must be >= 0
    with pytest.raises(ValidationError):
        PersonalizedPageResponse(
            content=[],
            page=-1,
            size=20,
            totalElements=0,
            totalPages=0,
            hasNext=False,
        )

    # size must be > 0
    with pytest.raises(ValidationError):
        PersonalizedPageResponse(
            content=[],
            page=0,
            size=0,
            totalElements=0,
            totalPages=0,
            hasNext=False,
        )
