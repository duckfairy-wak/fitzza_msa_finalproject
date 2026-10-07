package com.fitzza.user.dto;

public record LoginResponse(String accessToken, Long userId, String nickname) {
}
