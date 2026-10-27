package com.fitzza.product.product.dto;

import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductOptionEntity;
import com.fitzza.product.product.entity.ProductStatus;
import io.swagger.v3.oas.annotations.media.Schema;
import java.util.function.UnaryOperator;

@Schema(description = "상품 옵션 정보(내부 통신용). 장바구니·주문에서 가격과 판매 가능 여부를 확인할 때 사용한다.")
public record ProductOptionInternalResponse(
        @Schema(description = "옵션 ID", example = "10") Long optionId,
        @Schema(description = "상품 ID", example = "1") Long productId,
        @Schema(description = "브랜드명", example = "Fitzza") String brandName,
        @Schema(description = "상품명", example = "오버핏 헤비 후드 티셔츠") String productName,
        @Schema(description = "색상. 색상 구분이 없는 상품은 null", example = "BLACK") String color,
        @Schema(description = "사이즈", example = "M") String size,
        @Schema(description = "옵션 적용 판매가(원). 상품 판매가에 옵션 추가 금액을 더한 값", example = "42000") Integer price,
        @Schema(description = "썸네일 URL. 색 이미지가 있으면 그 주소, 없으면 상품 대표 이미지. S3 key면 Presigned GET URL")
                String imageUrl,
        @Schema(description = "판매 가능 여부. 상품 상태가 ON_SALE일 때만 true", example = "true") Boolean available,
        @Schema(description = "상품 판매 상태") ProductStatus status) {

    public static ProductOptionInternalResponse from(ProductOptionEntity option, UnaryOperator<String> resolveImageUrl) {
        ProductEntity product = option.getProduct();
        String stored = option.getImageUrl() != null ? option.getImageUrl() : product.getImageUrl();
        return new ProductOptionInternalResponse(
                option.getOptionId(),
                product.getProductId(),
                product.getBrand().getBrandName(),
                product.getProductName(),
                option.getColor(),
                option.getSize(),
                option.calculatePrice(),
                resolveImageUrl.apply(stored),
                product.getStatus() == ProductStatus.ON_SALE,
                product.getStatus());
    }
}
