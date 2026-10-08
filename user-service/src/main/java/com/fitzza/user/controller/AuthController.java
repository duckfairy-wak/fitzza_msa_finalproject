package com.fitzza.user.controller;

import com.fitzza.user.dto.LoginRequest;
import com.fitzza.user.dto.LoginResponse;
import com.fitzza.user.dto.RefreshTokenRequest;
import com.fitzza.user.dto.TokenResponse;
import com.fitzza.user.service.AuthService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    private final AuthService authService;

    /**
     * 로그인 요청을 처리할 인증 서비스를 주입한다.
     */
    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    /**
     * 검증된 로그인 요청으로 인증하고 액세스 토큰과 사용자 정보를 반환한다.
     */
    @PostMapping("/login")
    public LoginResponse login(@Valid @RequestBody LoginRequest request) {
        return authService.login(request);
    }

    @PostMapping("/reissue")
    public TokenResponse reissue(@Valid @RequestBody RefreshTokenRequest request) {
        return authService.reissue(request);
    }

    // Access Token이 이미 만료된 사용자도 로그아웃할 수 있도록 Refresh Token만 받는다.
    @PostMapping("/logout")
    public void logout(@Valid @RequestBody RefreshTokenRequest request) {
        authService.logout(request);
    }
}
