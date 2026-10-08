package com.fitzza.product.product.dto;

import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductStatus;
import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "상품 목록 항목")
public record ProductListResponse(
        @Schema(description = "상품 ID", example = "1") Long productId,
        @Schema(description = "상품명", example = "빅사이즈 볼캡 시리즈 60호 62호") String productName,
        @Schema(description = "브랜드명", example = "챕터에잇") String brandName,
        @Schema(description = "판매가(원)", example = "26100") Integer price,
        @Schema(description = "대표 이미지 URL") String thumbnailUrl,
        @Schema(description = "판매 상태") ProductStatus status) {

    public static ProductListResponse from(ProductEntity product) {
        return new ProductListResponse(
                product.getProductId(),
                product.getProductName(),
                product.getBrand().getBrandName(),
                product.getPrice(),
                product.getImageUrl(),
                product.getStatus());
    }
}
