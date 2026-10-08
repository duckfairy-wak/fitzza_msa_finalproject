package com.fitzza.product.product.dto;

import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductOptionEntity;
import com.fitzza.product.product.entity.ProductStatus;
import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "상품 옵션 정보(내부 통신용). 장바구니·주문에서 가격과 판매 가능 여부를 확인할 때 사용한다.")
public record ProductOptionInternalResponse(
        @Schema(description = "옵션 ID", example = "10") Long optionId,
        @Schema(description = "상품 ID", example = "1") Long productId,
        @Schema(description = "상품명", example = "오버핏 헤비 후드 티셔츠") String productName,
        @Schema(description = "옵션 적용 판매가(원). 상품 판매가에 옵션 추가 금액을 더한 값", example = "42000") Integer price,
        @Schema(description = "색상. 색상 구분이 없는 상품은 null", example = "BLACK") String color,
        @Schema(description = "사이즈", example = "M") String size,
        @Schema(description = "판매 가능 여부. 상품 상태가 ON_SALE일 때만 true", example = "true") Boolean available,
        @Schema(description = "상품 판매 상태") ProductStatus productStatus) {

    public static ProductOptionInternalResponse from(ProductOptionEntity option) {
        ProductEntity product = option.getProduct();
        return new ProductOptionInternalResponse(
                option.getOptionId(),
                product.getProductId(),
                product.getProductName(),
                option.calculatePrice(),
                option.getColor(),
                option.getSize(),
                product.getStatus() == ProductStatus.ON_SALE,
                product.getStatus());
    }
}
