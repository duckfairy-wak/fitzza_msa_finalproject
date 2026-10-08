package com.fitzza.user.dto;

public record LoginResponse(String accessToken, String refreshToken, Long userId, String nickname) {
}
