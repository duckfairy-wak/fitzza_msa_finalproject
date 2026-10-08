package com.fitzza.product.product.dto;

import com.fitzza.product.product.entity.ProductOptionEntity;
import io.swagger.v3.oas.annotations.media.Schema;
import java.util.Map;

@Schema(description = "상품 옵션과 실측 정보")
public record ProductOptionResponse(
        @Schema(description = "옵션 ID", example = "10") Long optionId,
        @Schema(description = "색상", example = "BLACK") String color,
        @Schema(description = "사이즈", example = "M") String size,
        @Schema(description = "실측 정보(항목명-값). 실측이 없으면 null", example = "{\"총장\": 70, \"어깨너비\": 52}")
        Map<String, Object> measurementSpec) {

    public static ProductOptionResponse of(ProductOptionEntity option, Map<String, Object> measurementSpec) {
        return new ProductOptionResponse(option.getOptionId(), option.getColor(), option.getSize(), measurementSpec);
    }
}
