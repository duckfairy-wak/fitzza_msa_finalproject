package com.fitzza.user.dto;

import com.fitzza.user.domain.UserRole;
import io.swagger.v3.oas.annotations.media.Schema;

// role은 화면 표시(관리자 메뉴)용이다. 실제 권한 검사는 서버가 X-User-Role 헤더로 한다.
public record LoginResponse(
        String accessToken,
        Long userId,
        String nickname,
        @Schema(description = "사용자 역할(USER 또는 ADMIN)", example = "USER") UserRole role) {
}
