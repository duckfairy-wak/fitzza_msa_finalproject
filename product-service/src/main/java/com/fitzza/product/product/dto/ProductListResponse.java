package com.fitzza.product.product.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductStatus;
import io.swagger.v3.oas.annotations.media.Schema;
import java.util.function.UnaryOperator;

@Schema(description = "상품 목록 항목")
public record ProductListResponse(
        @Schema(description = "상품 ID", example = "1") Long productId,
        @Schema(description = "상품명", example = "빅사이즈 볼캡 시리즈 60호 62호") String productName,
        @Schema(description = "브랜드명", example = "챕터에잇") String brandName,
        @Schema(description = "판매가(원)", example = "26100") Integer price,
        @Schema(description = "대표 이미지 URL. S3 object key면 Presigned GET URL") String thumbnailUrl,
        @Schema(description = "판매 상태") ProductStatus status,
        @JsonInclude(JsonInclude.Include.NON_NULL)
        @Schema(description = "요청 사용자의 찜 여부. 로그인하지 않으면 응답에 포함하지 않는다.") Boolean wished) {

    public static ProductListResponse from(ProductEntity product, Boolean wished, UnaryOperator<String> resolveImageUrl) {
        return new ProductListResponse(
                product.getProductId(),
                product.getProductName(),
                product.getBrand().getBrandName(),
                product.getPrice(),
                resolveImageUrl.apply(product.getImageUrl()),
                product.getStatus(),
                wished);
    }
}
