package com.fitzza.product.product.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import java.util.List;

@Schema(description = "상품별 옵션 실측 정보(내부 통신용)")
public record ProductMeasurementResponse(
        @Schema(description = "상품 ID", example = "1") Long productId,
        @Schema(description = "실측이 등록된 옵션 목록") List<ProductOptionResponse> options) {
}
