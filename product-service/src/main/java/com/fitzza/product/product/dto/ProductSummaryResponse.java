package com.fitzza.product.product.dto;

import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductStatus;
import io.swagger.v3.oas.annotations.media.Schema;
import java.util.function.UnaryOperator;

@Schema(description = "상품 요약 정보")
public record ProductSummaryResponse(
        @Schema(description = "상품 ID", example = "1") Long productId,
        @Schema(description = "브랜드명", example = "Fitzza") String brandName,
        @Schema(description = "상품명", example = "오버핏 코튼 셔츠") String productName,
        @Schema(description = "가격(원)", example = "39000") Integer price,
        @Schema(description = "대표 이미지 URL. S3 object key면 Presigned GET URL") String imageUrl,
        @Schema(description = "판매 상태") ProductStatus status) {

    public static ProductSummaryResponse from(ProductEntity product, UnaryOperator<String> resolveImageUrl) {
        return new ProductSummaryResponse(
                product.getProductId(),
                product.getBrand().getBrandName(),
                product.getProductName(),
                product.getPrice(),
                resolveImageUrl.apply(product.getImageUrl()),
                product.getStatus());
    }
}
