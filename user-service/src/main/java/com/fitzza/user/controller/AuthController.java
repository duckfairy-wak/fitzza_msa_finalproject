package com.fitzza.user.controller;

import com.fitzza.user.config.OpenApiConfig;
import com.fitzza.user.dto.ErrorResponse;
import com.fitzza.user.dto.LoginRequest;
import com.fitzza.user.dto.LoginResponse;
import com.fitzza.user.dto.RefreshTokenRequest;
import com.fitzza.user.dto.TokenResponse;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.security.RefreshTokenCookie;
import com.fitzza.user.service.AuthService;
import com.fitzza.user.service.LoginResult;
import com.fitzza.user.service.TokenResult;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.headers.Header;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "인증", description = "로그인(signin), 토큰 재발급(refresh), 로그아웃(signout)")
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private static final String BEARER_PREFIX = "Bearer ";
    private final AuthService authService;
    private final RefreshTokenCookie refreshTokenCookie;

    public AuthController(AuthService authService, RefreshTokenCookie refreshTokenCookie) {
        this.authService = authService;
        this.refreshTokenCookie = refreshTokenCookie;
    }

    @Operation(summary = "로그인", description = "Access Token과 사용자 정보를 응답 본문으로 반환한다. "
            + "Refresh Token은 HttpOnly refreshToken 쿠키로만 전달한다. "
            + "브라우저 클라이언트는 요청 시 credentials: 'include' 또는 withCredentials: true를 설정해야 한다.")
    @ApiResponses({
        @ApiResponse(responseCode = "200", content = @Content(schema = @Schema(implementation = LoginResponse.class)), headers = @Header(
                name = "Set-Cookie", description = "Refresh Token을 담은 HttpOnly refreshToken 쿠키")),
        @ApiResponse(responseCode = "400", description = "INVALID_REQUEST: 이메일 또는 비밀번호 누락",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(responseCode = "401", description = "INVALID_CREDENTIALS: 이메일 또는 비밀번호가 틀림(원인은 구분하지 않음)",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    })
    @PostMapping("/signin")
    public ResponseEntity<LoginResponse> login(@Valid @RequestBody LoginRequest request) {
        LoginResult result = authService.login(request);
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, refreshTokenCookie.issue(result.refreshToken()))
                .body(new LoginResponse(result.accessToken(), result.userId(), result.nickname(), result.role()));
    }

    @Operation(summary = "토큰 재발급", description = "refreshToken 쿠키를 읽어 토큰을 재발급하며 JSON 요청 본문은 필요하지 않다. "
            + "새 Refresh Token으로 쿠키를 교체하고 응답 본문에는 새 Access Token만 반환한다. "
            + "쿠키가 없거나 비어 있으면 400, 토큰이 유효하지 않거나 이미 사용되었으면 401을 반환한다.")
    @ApiResponses({
        @ApiResponse(responseCode = "200", content = @Content(schema = @Schema(implementation = TokenResponse.class)), headers = @Header(
                name = "Set-Cookie", description = "새 Refresh Token으로 교체한 HttpOnly refreshToken 쿠키")),
        @ApiResponse(responseCode = "400", description = "INVALID_REQUEST: refreshToken 쿠키 누락 또는 빈 값",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class))),
        @ApiResponse(responseCode = "401", description = "INVALID_REFRESH_TOKEN: 만료되었거나 이미 사용된 토큰 등 유효하지 않은 토큰",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    })
    @SecurityRequirement(name = OpenApiConfig.REFRESH_COOKIE)
    @PostMapping("/refresh")
    public ResponseEntity<TokenResponse> reissue(
            @CookieValue(name = RefreshTokenCookie.NAME, required = false) String refreshToken) {
        TokenResult result = authService.reissue(refreshRequest(refreshToken));
        return ResponseEntity.ok()
                .header(HttpHeaders.SET_COOKIE, refreshTokenCookie.issue(result.refreshToken()))
                .body(new TokenResponse(result.accessToken()));
    }

    @Operation(summary = "로그아웃", description = "refreshToken 쿠키의 토큰을 폐기하고 쿠키를 만료시킨다. "
            + "JSON 요청 본문은 필요하지 않으며, 쿠키가 없거나 비어 있으면 400을 반환한다. "
            + "Authorization 헤더로 Bearer Access Token을 함께 보내면 해당 토큰도 폐기한다. 이미 폐기된 토큰으로 다시 요청해도 성공한다.",
            security = @SecurityRequirement(name = OpenApiConfig.REFRESH_COOKIE))
    @ApiResponses({
        @ApiResponse(responseCode = "200", content = @Content, headers = @Header(
                name = "Set-Cookie", description = "만료 처리한 HttpOnly refreshToken 쿠키")),
        @ApiResponse(responseCode = "400", description = "INVALID_REQUEST: refreshToken 쿠키 누락 또는 빈 값",
                content = @Content(schema = @Schema(implementation = ErrorResponse.class)))
    })
    @PostMapping("/signout")
    public ResponseEntity<Void> logout(
            @CookieValue(name = RefreshTokenCookie.NAME, required = false) String refreshToken,
            @Parameter(hidden = true) @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false)
                    String authorization) {
        authService.logout(refreshRequest(refreshToken), bearerTokenOf(authorization));
        return ResponseEntity.ok().header(HttpHeaders.SET_COOKIE, refreshTokenCookie.clear()).build();
    }

    private static RefreshTokenRequest refreshRequest(String token) {
        if (token == null || token.isBlank()) {
            throw new UserApiException(ErrorCode.INVALID_REQUEST);
        }
        return new RefreshTokenRequest(token);
    }

    private static String bearerTokenOf(String authorization) {
        if (authorization == null
                || !authorization.regionMatches(true, 0, BEARER_PREFIX, 0, BEARER_PREFIX.length())) {
            return null;
        }
        return authorization.substring(BEARER_PREFIX.length()).trim();
    }
}
