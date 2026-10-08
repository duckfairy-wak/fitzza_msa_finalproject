package com.fitzza.product.global.exception;

import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;

@Getter
@RequiredArgsConstructor
public enum ErrorCode {

    INVALID_REQUEST(HttpStatus.BAD_REQUEST, "잘못된 요청입니다."),
    PRODUCT_NOT_FOUND(HttpStatus.NOT_FOUND, "상품을 찾을 수 없습니다."),
    BRAND_NOT_FOUND(HttpStatus.NOT_FOUND, "브랜드를 찾을 수 없습니다."),
    INVALID_CATEGORY_CODE(HttpStatus.BAD_REQUEST, "카테고리 코드가 올바르지 않습니다."),
    COMBO_NOT_FOUND(HttpStatus.NOT_FOUND, "코디 조합을 찾을 수 없습니다."),
    COMBO_VALIDATION_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "코디 조합 검증 서비스를 사용할 수 없습니다."),
    WISHLIST_NOT_FOUND(HttpStatus.NOT_FOUND, "찜 항목을 찾을 수 없습니다."),
    WISHLIST_ALREADY_EXISTS(HttpStatus.CONFLICT, "이미 찜한 항목입니다."),
    WORLDCUP_NOT_FOUND(HttpStatus.NOT_FOUND, "월드컵 결과를 찾을 수 없습니다."),
    WORLDCUP_INVALID_CANDIDATES(HttpStatus.BAD_REQUEST, "월드컵 후보 구성이 올바르지 않습니다."),
    INTERNAL_SERVER_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "서버 내부 오류가 발생했습니다.");

    private final HttpStatus status;
    private final String message;
}
