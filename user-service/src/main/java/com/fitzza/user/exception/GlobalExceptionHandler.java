package com.fitzza.user.exception;

import com.fitzza.user.dto.ErrorResponse;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

    /**
     * 사용자 서비스의 업무 오류를 해당 HTTP 상태와 공통 오류 응답으로 변환한다.
     */
    @ExceptionHandler(UserApiException.class)
    public ResponseEntity<ErrorResponse> handleUserApiException(UserApiException exception) {
        ErrorCode errorCode = exception.getErrorCode();
        return toResponse(errorCode, errorCode.getMessage());
    }

    /**
     * 요청 본문 검증 실패를 첫 필드 오류 메시지와 함께 HTTP 400으로 반환한다.
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleInvalidBody(MethodArgumentNotValidException exception) {
        String message = exception.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(FieldError::getDefaultMessage)
                .orElse(ErrorCode.INVALID_INPUT.getMessage());
        return toResponse(ErrorCode.INVALID_INPUT, message);
    }

    /**
     * 필수 쿼리 매개변수 누락이나 읽을 수 없는 본문을 INVALID_INPUT 응답으로 변환한다.
     */
    @ExceptionHandler({MissingServletRequestParameterException.class, HttpMessageNotReadableException.class})
    public ResponseEntity<ErrorResponse> handleMalformedRequest() {
        return toResponse(ErrorCode.INVALID_INPUT, ErrorCode.INVALID_INPUT.getMessage());
    }

    /**
     * 오류 코드의 HTTP 상태와 지정된 메시지를 사용해 공통 응답을 구성한다.
     */
    private ResponseEntity<ErrorResponse> toResponse(ErrorCode errorCode, String message) {
        return ResponseEntity.status(errorCode.getStatus()).body(new ErrorResponse(errorCode.name(), message));
    }
}
