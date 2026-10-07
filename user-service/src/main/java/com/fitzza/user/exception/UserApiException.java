package com.fitzza.user.exception;

public class UserApiException extends RuntimeException {

    private final ErrorCode errorCode;

    public UserApiException(ErrorCode errorCode) {
        super(errorCode.getMessage());
        this.errorCode = errorCode;
    }

    public ErrorCode getErrorCode() {
        return errorCode;
    }
}
