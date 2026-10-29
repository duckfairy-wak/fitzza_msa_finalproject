package com.fitzza.user.service;

import com.fitzza.user.domain.UserRole;

public record LoginResult(String accessToken, String refreshToken, Long userId, String nickname, UserRole role) {
}
