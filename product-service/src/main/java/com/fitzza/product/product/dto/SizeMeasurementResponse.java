package com.fitzza.product.product.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import java.util.Map;

@Schema(description = "사이즈별 실측값")
public record SizeMeasurementResponse(
        @Schema(description = "사이즈 라벨", example = "60호") String size,
        @Schema(description = "실측 표 노출 순서. 정보가 없으면 null", example = "0") Integer sequence,
        @Schema(description = "실측 항목명-값", example = "{\"머리둘레\": 60.0, \"챙길이\": 7.0}")
        Map<String, Object> values) {
}
