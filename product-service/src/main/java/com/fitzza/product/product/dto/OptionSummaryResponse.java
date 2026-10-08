package com.fitzza.product.product.dto;

import com.fitzza.product.product.entity.ProductEntity;
import com.fitzza.product.product.entity.ProductOptionEntity;
import com.fitzza.product.product.entity.ProductStatus;
import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "옵션 요약 정보(내부 통신용). 장바구니·주문의 가격 및 판매 가능 여부 확인에 사용한다.")
public record OptionSummaryResponse(
        @Schema(description = "옵션 ID", example = "10") Long optionId,
        @Schema(description = "상품 ID", example = "1") Long productId,
        @Schema(description = "브랜드명", example = "Fitzza") String brandName,
        @Schema(description = "상품명", example = "오버핏 코튼 셔츠") String productName,
        @Schema(description = "색상", example = "BLACK") String color,
        @Schema(description = "사이즈", example = "M") String size,
        @Schema(description = "옵션 적용 판매가(원). 상품 가격에 옵션 추가 금액을 더한 값", example = "39000") Integer price,
        @Schema(description = "대표 이미지 URL") String imageUrl,
        @Schema(description = "상품 판매 상태") ProductStatus status) {

    public static OptionSummaryResponse from(ProductOptionEntity option) {
        ProductEntity product = option.getProduct();
        return new OptionSummaryResponse(
                option.getOptionId(),
                product.getProductId(),
                product.getBrand().getBrandName(),
                product.getProductName(),
                option.getColor(),
                option.getSize(),
                option.calculatePrice(),
                product.getImageUrl(),
                product.getStatus());
    }
}
