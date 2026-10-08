package com.fitzza.user.exception;

import org.springframework.http.HttpStatus;

public enum ErrorCode {
    INVALID_INPUT(HttpStatus.BAD_REQUEST, "입력값을 확인해주세요."),
    INVALID_CREDENTIALS(HttpStatus.UNAUTHORIZED, "이메일 혹은 비밀번호가 틀렸습니다."),
    UNAUTHENTICATED(HttpStatus.UNAUTHORIZED, "로그인이 필요합니다."),
    INVALID_REFRESH_TOKEN(HttpStatus.UNAUTHORIZED, "로그인이 만료되었습니다. 다시 로그인해주세요."),
    USER_NOT_FOUND(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다."),
    DUPLICATE_EMAIL(HttpStatus.CONFLICT, "이미 사용 중인 이메일입니다."),
    DUPLICATE_NICKNAME(HttpStatus.CONFLICT, "이미 사용 중인 닉네임입니다."),
    DUPLICATE_ACCOUNT(HttpStatus.CONFLICT, "이미 사용 중인 이메일 또는 닉네임입니다.");

    private final HttpStatus status;
    private final String message;

    /**
     * API 오류에 사용할 HTTP 상태와 기본 응답 메시지를 연결한다.
     */
    ErrorCode(HttpStatus status, String message) {
        this.status = status;
        this.message = message;
    }

    /**
     * 이 오류를 클라이언트에 전달할 HTTP 상태를 반환한다.
     */
    public HttpStatus getStatus() {
        return status;
    }

    /**
     * 오류 응답과 예외에서 공통으로 사용할 기본 메시지를 반환한다.
     */
    public String getMessage() {
        return message;
    }
}
