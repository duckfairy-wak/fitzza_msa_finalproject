package com.fitzza.product.product.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import java.util.List;

@Schema(description = "사이즈 안내. 사이즈별 실측값과 측정 기준을 포함한다.")
public record SizeGuideResponse(
        @Schema(description = "사이즈 표 종류", example = "캡/야구모자") String typeName,
        @Schema(description = "실측 단위", example = "cm") String unit,
        @Schema(description = "측정 방법 안내 문구") String description,
        @Schema(description = "사이즈 측정 가이드 이미지 URL") String guideImageUrl,
        @Schema(description = "사이즈별 실측값 목록") List<SizeMeasurementResponse> measurements) {
}
