package com.fitzza.product.product.dto;

import com.fitzza.product.product.entity.ProductOptionEntity;
import io.swagger.v3.oas.annotations.media.Schema;
import java.util.function.UnaryOperator;

@Schema(description = "상품 상세의 옵션 항목")
public record ProductDetailOptionResponse(
        @Schema(description = "옵션 ID", example = "10") Long optionId,
        @Schema(description = "색상. 색상 구분이 없는 상품은 null", example = "BLACK") String color,
        @Schema(description = "사이즈", example = "M") String size,
        @Schema(description = "옵션 추가 금액(원)", example = "0") Integer additionalPrice,
        @Schema(description = "옵션 적용 판매가(원). 상품 판매가에 추가 금액을 더한 값", example = "26100") Integer price,
        @Schema(description = "이 색의 썸네일. 색 이미지가 없으면 null이며 상품 대표 이미지를 쓴다. S3 key면 Presigned GET URL")
                String imageUrl) {

    public static ProductDetailOptionResponse from(ProductOptionEntity option, UnaryOperator<String> resolveImageUrl) {
        return new ProductDetailOptionResponse(
                option.getOptionId(),
                option.getColor(),
                option.getSize(),
                option.getAdditionalPrice(),
                option.calculatePrice(),
                resolveImageUrl.apply(option.getImageUrl()));
    }
}
