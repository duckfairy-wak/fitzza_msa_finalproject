package com.fitzza.community.exception;

public class CommunityApiException extends RuntimeException {

    private final ErrorCode errorCode;

    public CommunityApiException(ErrorCode errorCode) {
        super(errorCode.getMessage());
        this.errorCode = errorCode;
    }

    public ErrorCode getErrorCode() {
        return errorCode;
    }
}
