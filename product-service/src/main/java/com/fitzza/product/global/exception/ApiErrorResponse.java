package com.fitzza.product.global.exception;

import io.swagger.v3.oas.annotations.media.Schema;

@Schema(description = "오류 응답")
public record ApiErrorResponse(
        @Schema(description = "HTTP 상태 코드", example = "404") int status,
        @Schema(description = "오류 코드", example = "PRODUCT_NOT_FOUND") String code,
        @Schema(description = "오류 메시지", example = "상품을 찾을 수 없습니다.") String message) {
}
