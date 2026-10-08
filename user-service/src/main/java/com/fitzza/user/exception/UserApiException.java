package com.fitzza.user.exception;

public class UserApiException extends RuntimeException {

    private final ErrorCode errorCode;

    /**
     * 응답 변환에 필요한 오류 코드를 보관하고 기본 메시지로 예외를 생성한다.
     */
    public UserApiException(ErrorCode errorCode) {
        super(errorCode.getMessage());
        this.errorCode = errorCode;
    }

    /**
     * 예외 처리기가 HTTP 상태와 응답 코드를 결정할 오류 정보를 반환한다.
     */
    public ErrorCode getErrorCode() {
        return errorCode;
    }
}
