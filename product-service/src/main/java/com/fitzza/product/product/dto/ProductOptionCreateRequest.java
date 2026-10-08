package com.fitzza.product.product.dto;

import com.fasterxml.jackson.annotation.JsonIgnore;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import org.springframework.util.StringUtils;

@Schema(description = "상품 등록 시 함께 등록할 옵션")
public record ProductOptionCreateRequest(
        @Schema(description = "색상. 색상 구분이 없으면 생략", example = "BLACK") @Size(max = 100) String color,
        @Schema(description = "사이즈. 사이즈 구분이 없으면 생략", example = "M") @Size(max = 100) String size,
        @Schema(description = "상품 판매가에 더해지는 옵션 추가 금액(원). 생략하면 0", example = "0")
        @PositiveOrZero Integer additionalPrice) {

    @Schema(hidden = true)
    @JsonIgnore
    @AssertTrue(message = "색상 또는 사이즈 중 하나는 필요합니다.")
    public boolean isNamed() {
        return StringUtils.hasText(color) || StringUtils.hasText(size);
    }
}
