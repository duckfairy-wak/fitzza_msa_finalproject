package com.fitzza.product.product.dto;

import com.fitzza.product.product.entity.FitType;
import com.fitzza.product.product.entity.Gender;
import com.fitzza.product.product.entity.ProductStatus;
import com.fitzza.product.product.entity.Season;
import io.swagger.v3.oas.annotations.media.Schema;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@Schema(description = "상품 상세 정보")
public record ProductDetailResponse(
        @Schema(description = "상품 ID", example = "1") Long productId,
        @Schema(description = "상품명", example = "빅사이즈 볼캡 시리즈 60호 62호") String productName,
        @Schema(description = "영문 상품명", example = "Bigsized Baseball Cap 60cm 62cm") String productNameEn,
        @Schema(description = "브랜드 품번", example = "BIGBALL") String styleNo,
        @Schema(description = "브랜드 ID", example = "1") Long brandId,
        @Schema(description = "브랜드명", example = "챕터에잇") String brandName,
        @Schema(description = "영문 브랜드명", example = "CHAPTER EIGHT") String brandNameEn,
        @Schema(description = "대분류 카테고리 코드", example = "120") String categoryL1,
        @Schema(description = "중분류 카테고리 코드", example = "120001") String categoryL2,
        @Schema(description = "소분류 카테고리 코드. 없으면 null") String subcategory,
        @Schema(description = "가장 하위 카테고리 코드", example = "120001") String categoryCode,
        @Schema(description = "대분류 이름(표시용)", example = "모자") String categoryL1Name,
        @Schema(description = "중분류 이름(표시용)", example = "캡/야구모자") String categoryL2Name,
        @Schema(description = "소분류 이름(표시용). 없으면 null") String subcategoryName,
        @Schema(description = "판매가(원)", example = "26100") Integer price,
        @Schema(description = "정상가(원)", example = "29000") Integer normalPrice,
        @Schema(description = "할인율(%)", example = "10") Integer discountRate,
        @Schema(description = "성별") Gender gender,
        @Schema(description = "대표 시즌. 정보가 없으면 null") Season season,
        @Schema(description = "소재") String material,
        @Schema(description = "핏") FitType fitType,
        @Schema(description = "상품 특징(항목명-값 목록)", example = "{\"깊이\": [\"깊음\"]}")
        Map<String, List<String>> features,
        @Schema(description = "상품 설명") String description,
        @Schema(description = "대표 이미지 URL") String thumbnailUrl,
        @Schema(description = "상품 이미지 URL 목록(노출 순서). 첫 번째가 대표 이미지") List<String> images,
        @Schema(description = "사이즈 안내와 사이즈별 실측값. 정보가 없으면 null") SizeGuideResponse sizeGuide,
        @Schema(description = "옵션 목록") List<ProductDetailOptionResponse> options,
        @Schema(description = "판매 상태") ProductStatus status,
        @Schema(description = "등록 일시") LocalDateTime createdAt,
        @Schema(description = "수정 일시") LocalDateTime updatedAt) {
}
