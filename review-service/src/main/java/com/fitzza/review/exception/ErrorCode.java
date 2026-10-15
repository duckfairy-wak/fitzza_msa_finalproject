package com.fitzza.review.exception;

import org.springframework.http.HttpStatus;

public enum ErrorCode {
    INVALID_REQUEST(HttpStatus.BAD_REQUEST, "입력값을 확인해주세요."),
    ORDER_ITEM_PRODUCT_MISMATCH(HttpStatus.BAD_REQUEST, "주문한 상품과 리뷰할 상품이 다릅니다."),
    UNAUTHENTICATED(HttpStatus.UNAUTHORIZED, "로그인이 필요합니다."),
    NOT_ORDER_OWNER(HttpStatus.FORBIDDEN, "내 주문만 리뷰·설문할 수 있습니다."),
    NOT_AUTHOR(HttpStatus.FORBIDDEN, "작성자만 할 수 있습니다."),
    ORDER_ITEM_NOT_FOUND(HttpStatus.NOT_FOUND, "주문 항목을 찾을 수 없습니다."),
    REVIEW_NOT_FOUND(HttpStatus.NOT_FOUND, "리뷰를 찾을 수 없습니다."),
    ORDER_CANCELED(HttpStatus.CONFLICT, "취소된 주문은 리뷰·설문할 수 없습니다."),
    DUPLICATE_REVIEW(HttpStatus.CONFLICT, "이미 리뷰를 작성한 주문 상품입니다."),
    DUPLICATE_SURVEY(HttpStatus.CONFLICT, "이미 설문을 작성한 주문 상품입니다."),
    CONCURRENT_UPDATE(HttpStatus.CONFLICT, "다른 요청과 겹쳐 처리하지 못했습니다. 새로고침 후 다시 시도해주세요."),
    ORDER_LOOKUP_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "주문 정보를 확인하지 못했습니다. 잠시 후 다시 시도해주세요."),
    INTERNAL_SERVER_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "서버에서 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.");

    private final HttpStatus status;
    private final String message;

    ErrorCode(HttpStatus status, String message) {
        this.status = status;
        this.message = message;
    }

    public HttpStatus getStatus() {
        return status;
    }

    public String getMessage() {
        return message;
    }
}
