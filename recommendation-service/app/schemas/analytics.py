from typing import Any
from pydantic import BaseModel, Field


class TokenUsageItem(BaseModel):
    label: str = Field(..., description="시간대/요일/주차/월 레이블 (예: '00시', '월', '1주', '1월')")
    input: int = Field(default=0, description="입력(프롬프트) 토큰 사용량")
    output: int = Field(default=0, description="출력(완성) 토큰 사용량")


class KeywordCountItem(BaseModel):
    name: str = Field(..., description="TPO 및 스타일 키워드명 (예: '출근룩', '미니멀')")
    count: int = Field(default=0, description="추천 횟수")


class ProductCountItem(BaseModel):
    name: str = Field(..., description="추천된 상품명")
    brand: str = Field(default="", description="상품 브랜드명")
    count: int = Field(default=0, description="추천 횟수")


class PeriodAnalytics(BaseModel):
    label: str = Field(..., description="기간 구분 (일간, 주간, 월간, 연간)")
    startDate: str = Field(..., description="조회 시작일 (YYYY-MM-DD)")
    endDate: str = Field(..., description="조회 종료일 (YYYY-MM-DD)")
    usage: list[TokenUsageItem] = Field(default_factory=list, description="토큰 사용량 추이 목록")
    keywords: list[KeywordCountItem] = Field(default_factory=list, description="인기 AI 스타일 키워드 목록")
    products: list[ProductCountItem] = Field(default_factory=list, description="많이 추천받은 상품 목록")


class AnalyticsResponse(BaseModel):
    daily: PeriodAnalytics = Field(..., description="일간 분석 통계")
    weekly: PeriodAnalytics = Field(..., description="주간 분석 통계")
    monthly: PeriodAnalytics = Field(..., description="월간 분석 통계")
    yearly: PeriodAnalytics = Field(..., description="연간 분석 통계")
