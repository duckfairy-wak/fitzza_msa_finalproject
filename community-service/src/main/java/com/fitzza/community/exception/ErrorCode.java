package com.fitzza.community.exception;

import org.springframework.http.HttpStatus;

public enum ErrorCode {
    INVALID_INPUT(HttpStatus.BAD_REQUEST, "입력값을 확인해주세요."),
    INVALID_PARENT_COMMENT(HttpStatus.BAD_REQUEST, "답글을 달 수 없는 댓글입니다."),
    NOT_VOTE_POST(HttpStatus.BAD_REQUEST, "투표 게시글이 아닙니다."),
    INVALID_VOTE_OPTIONS(HttpStatus.BAD_REQUEST, "투표 선택지를 확인해주세요."),
    INVALID_VOTE_OPTION(HttpStatus.BAD_REQUEST, "이 게시글의 선택지가 아닙니다."),
    UNAUTHENTICATED(HttpStatus.UNAUTHORIZED, "로그인이 필요합니다."),
    NOT_AUTHOR(HttpStatus.FORBIDDEN, "작성자만 할 수 있습니다."),
    POST_NOT_FOUND(HttpStatus.NOT_FOUND, "게시글을 찾을 수 없습니다."),
    COMMENT_NOT_FOUND(HttpStatus.NOT_FOUND, "댓글을 찾을 수 없습니다."),
    VOTE_CLOSED(HttpStatus.CONFLICT, "마감된 투표입니다."),
    CONCURRENT_UPDATE(HttpStatus.CONFLICT, "다른 요청과 겹쳐 처리하지 못했습니다. 새로고침 후 다시 시도해주세요.");

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
