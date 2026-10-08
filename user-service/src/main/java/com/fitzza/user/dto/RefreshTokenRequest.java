package com.fitzza.user.dto;

import jakarta.validation.constraints.NotBlank;

public record RefreshTokenRequest(@NotBlank(message = "Refresh Token이 필요합니다.") String refreshToken) {
}
