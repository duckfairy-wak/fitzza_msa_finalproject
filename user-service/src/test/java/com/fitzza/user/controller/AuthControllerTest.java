package com.fitzza.user.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.not;
import jakarta.servlet.http.Cookie;

import com.fitzza.user.domain.UserRole;
import com.fitzza.user.dto.LoginRequest;
import com.fitzza.user.dto.RefreshTokenRequest;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.GlobalExceptionHandler;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.service.AuthService;
import com.fitzza.user.service.LoginResult;
import com.fitzza.user.service.TokenResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class AuthControllerTest {

    private final AuthService authService = mock(AuthService.class);
    private MockMvc mockMvc;

    /**
     * 실제 예외 처리기를 연결한 독립 MockMvc로 HTTP 응답 계약을 검증할 준비를 한다.
     */
    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(new AuthController(authService, new com.fitzza.user.security.RefreshTokenCookie(false, 2592000)))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    /**
     * Access Token과 사용자 정보는 JSON으로, Refresh Token은 HttpOnly 쿠키로만 전달되는지 검증한다.
     */
    @Test
    void loginReturnsRefreshCookieAndAccessTokenWithUserInfo() throws Exception {
        when(authService.login(any(LoginRequest.class)))
                .thenReturn(new LoginResult("access", "refresh", 7L, "fitzza", UserRole.USER));

        mockMvc.perform(post("/api/auth/signin")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email": "fit@example.com", "password": "password1"}
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.accessToken").value("access"))
                .andExpect(jsonPath("$.refreshToken").doesNotExist())
                .andExpect(header().string("Set-Cookie", containsString("refreshToken=refresh")))
                .andExpect(header().string("Set-Cookie", containsString("HttpOnly")))
                .andExpect(header().string("Set-Cookie", containsString("SameSite=Lax")))
                .andExpect(header().string("Set-Cookie", containsString("Path=/api")))
                .andExpect(header().string("Set-Cookie", containsString("Max-Age=2592000")))
                .andExpect(header().string("Set-Cookie", not(containsString("Secure"))))
                .andExpect(jsonPath("$.userId").value(7))
                .andExpect(jsonPath("$.nickname").value("fitzza"))
                .andExpect(jsonPath("$.role").value("USER"));
    }

    /**
     * 잘못된 인증 정보가 HTTP 401과 공통 오류 코드로 노출되는지 검증한다.
     */
    @Test
    void loginReturnsUnauthorizedForInvalidCredentials() throws Exception {
        when(authService.login(any(LoginRequest.class)))
                .thenThrow(new UserApiException(ErrorCode.INVALID_CREDENTIALS));

        mockMvc.perform(post("/api/auth/signin")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email": "fit@example.com", "password": "wrong-password1"}
                                """))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_CREDENTIALS"));
    }

    /**
     * 빈 비밀번호를 HTTP 계층에서 차단해 인증 서비스가 호출되지 않는지 검증한다.
     */
    @Test
    void loginRejectsBlankPasswordBeforeCallingService() throws Exception {
        mockMvc.perform(post("/api/auth/signin")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"email": "fit@example.com", "password": ""}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
        verifyNoInteractions(authService);
    }

    @Test
    void reissueReturnsANewTokenPair() throws Exception {
        when(authService.reissue(new RefreshTokenRequest("old-refresh")))
                .thenReturn(new TokenResult("new-access", "new-refresh"));

        mockMvc.perform(post("/api/auth/refresh")
                        .cookie(new Cookie("refreshToken", "old-refresh")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.accessToken").value("new-access"))
                .andExpect(jsonPath("$.refreshToken").doesNotExist())
                .andExpect(header().string("Set-Cookie", containsString("refreshToken=new-refresh")));
    }

    @Test
    void reissueReturnsUnauthorizedForInvalidRefreshToken() throws Exception {
        when(authService.reissue(any(RefreshTokenRequest.class)))
                .thenThrow(new UserApiException(ErrorCode.INVALID_REFRESH_TOKEN));

        mockMvc.perform(post("/api/auth/refresh")
                        .cookie(new Cookie("refreshToken", "used-refresh")))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("INVALID_REFRESH_TOKEN"));
    }

    @Test
    void reissueRejectsMissingRefreshTokenBeforeCallingService() throws Exception {
        mockMvc.perform(post("/api/auth/refresh")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
        verifyNoInteractions(authService);
    }

    @Test
    void logoutPassesTheRefreshTokenAndClearsCookie() throws Exception {
        mockMvc.perform(post("/api/auth/signout")
                        .cookie(new Cookie("refreshToken", "refresh")))
                .andExpect(status().isOk())
                .andExpect(header().string("Set-Cookie", containsString("Max-Age=0")))
                .andExpect(header().string("Set-Cookie", containsString("Path=/api")))
                .andExpect(header().string("Set-Cookie", containsString("HttpOnly")));
        verify(authService).logout(new RefreshTokenRequest("refresh"), null);
    }

    @Test
    void logoutPassesTheAccessTokenFromTheAuthorizationHeader() throws Exception {
        mockMvc.perform(post("/api/auth/signout")
                        .header("Authorization", "Bearer access-token ")
                        .cookie(new Cookie("refreshToken", "refresh")))
                .andExpect(status().isOk());
        verify(authService).logout(new RefreshTokenRequest("refresh"), "access-token");
    }

    // 게이트웨이는 bearer·BEARER도 받으므로, 로그아웃도 같은 토큰을 블랙리스트에 올려야 한다.
    @Test
    void logoutReadsTheBearerSchemeWithoutRegardToCase() throws Exception {
        mockMvc.perform(post("/api/auth/signout")
                        .header("Authorization", "bearer access-token")
                        .cookie(new Cookie("refreshToken", "refresh")))
                .andExpect(status().isOk());
        verify(authService).logout(new RefreshTokenRequest("refresh"), "access-token");
    }

    @Test
    void logoutIgnoresAnAuthorizationHeaderThatIsNotABearerToken() throws Exception {
        mockMvc.perform(post("/api/auth/signout")
                        .header("Authorization", "Basic dXNlcjpwYXNz")
                        .cookie(new Cookie("refreshToken", "refresh")))
                .andExpect(status().isOk());
        verify(authService).logout(new RefreshTokenRequest("refresh"), null);
    }

    @Test
    void missingAndBlankCookiesRejectBothEndpointsIncludingLegacyJson() throws Exception {
        for (String endpoint : new String[] {"refresh", "signout"}) {
            mockMvc.perform(post("/api/auth/" + endpoint)
                            .contentType(MediaType.APPLICATION_JSON)
                            .content("{\"refreshToken\":\"legacy-token\"}"))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
            mockMvc.perform(post("/api/auth/" + endpoint).cookie(new Cookie("refreshToken", " ")))
                    .andExpect(status().isBadRequest());
        }
        verifyNoInteractions(authService);
    }

    @Test
    void productionCookieIsSecureOnIssueAndDeletion() throws Exception {
        MockMvc secureMvc = MockMvcBuilders.standaloneSetup(
                new AuthController(authService, new com.fitzza.user.security.RefreshTokenCookie(true, 60)))
                .setControllerAdvice(new GlobalExceptionHandler()).build();
        when(authService.login(any(LoginRequest.class)))
                .thenReturn(new LoginResult("access", "refresh", 7L, "fitzza", UserRole.USER));
        secureMvc.perform(post("/api/auth/signin").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"fit@example.com\",\"password\":\"password1\"}"))
                .andExpect(status().isOk())
                .andExpect(header().string("Set-Cookie", containsString("Secure")))
                .andExpect(header().string("Set-Cookie", containsString("Max-Age=60")));
        secureMvc.perform(post("/api/auth/signout").cookie(new Cookie("refreshToken", "refresh")))
                .andExpect(status().isOk())
                .andExpect(header().string("Set-Cookie", containsString("Secure")))
                .andExpect(header().string("Set-Cookie", containsString("SameSite=Lax")))
                .andExpect(header().string("Set-Cookie", containsString("Max-Age=0")));
    }
}
