package com.fitzza.user.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fitzza.user.domain.User;
import com.fitzza.user.domain.UserStatus;
import com.fitzza.user.dto.LoginRequest;
import com.fitzza.user.dto.LoginResponse;
import com.fitzza.user.dto.RefreshTokenRequest;
import com.fitzza.user.dto.TokenResponse;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.repository.UserRepository;
import com.fitzza.user.security.AccessTokenBlacklist;
import com.fitzza.user.security.JwtTokenProvider;
import com.fitzza.user.security.RefreshTokenStore;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(MockitoExtension.class)
class AuthServiceTest {

    @Mock
    private UserRepository userRepository;

    @Mock
    private PasswordEncoder passwordEncoder;

    @Mock
    private JwtTokenProvider jwtTokenProvider;

    @Mock
    private RefreshTokenStore refreshTokenStore;

    @Mock
    private AccessTokenBlacklist accessTokenBlacklist;

    private AuthService authService;

    /**
     * 모의 의존성을 주입해 외부 저장소와 독립적으로 인증 서비스를 검증한다.
     */
    @BeforeEach
    void setUp() {
        authService = new AuthService(
                userRepository, passwordEncoder, jwtTokenProvider, refreshTokenStore, accessTokenBlacklist);
    }

    /**
     * 이메일 정규화와 비밀번호 대조를 거쳐 활성 계정의 토큰·사용자 정보가 반환되는지 검증한다.
     */
    @Test
    void loginReturnsBothTokensAndUserInfoForMatchingCredentials() {
        User user = storedUser(UserStatus.ACTIVE);
        when(userRepository.findByEmail("fit@example.com")).thenReturn(Optional.of(user));
        when(passwordEncoder.matches("password1", "ENCODED")).thenReturn(true);
        when(jwtTokenProvider.createAccessToken(7L)).thenReturn("access");
        when(refreshTokenStore.issue(7L)).thenReturn("refresh");

        LoginResponse response = authService.login(new LoginRequest(" Fit@Example.com", "password1"));

        assertThat(response).isEqualTo(new LoginResponse("access", "refresh", 7L, "fitzza"));
    }

    @Test
    void failedLoginIssuesNoRefreshToken() {
        when(userRepository.findByEmail("fit@example.com")).thenReturn(Optional.of(storedUser(UserStatus.ACTIVE)));
        when(passwordEncoder.matches("wrong-password1", "ENCODED")).thenReturn(false);

        assertInvalidCredentials(new LoginRequest("fit@example.com", "wrong-password1"));
        verify(refreshTokenStore, never()).issue(anyLong());
    }

    @Test
    void reissueSwapsTheUsedRefreshTokenForANewPair() {
        when(refreshTokenStore.consume("old-refresh")).thenReturn(Optional.of(7L));
        when(userRepository.findById(7L)).thenReturn(Optional.of(storedUser(UserStatus.ACTIVE)));
        when(jwtTokenProvider.createAccessToken(7L)).thenReturn("new-access");
        when(refreshTokenStore.issue(7L)).thenReturn("new-refresh");

        TokenResponse response = authService.reissue(new RefreshTokenRequest("old-refresh"));

        assertThat(response).isEqualTo(new TokenResponse("new-access", "new-refresh"));
        verify(refreshTokenStore).consume("old-refresh");
    }

    @Test
    void reissueRejectsUnknownExpiredOrAlreadyUsedRefreshToken() {
        when(refreshTokenStore.consume("used-refresh")).thenReturn(Optional.empty());

        assertInvalidRefreshToken("used-refresh");
        verify(refreshTokenStore, never()).issue(anyLong());
    }

    @Test
    void reissueRejectsAccountSuspendedAfterLogin() {
        when(refreshTokenStore.consume("old-refresh")).thenReturn(Optional.of(7L));
        when(userRepository.findById(7L)).thenReturn(Optional.of(storedUser(UserStatus.SUSPENDED)));

        assertInvalidRefreshToken("old-refresh");
        verify(refreshTokenStore, never()).issue(anyLong());
    }

    @Test
    void logoutRevokesTheRefreshToken() {
        authService.logout(new RefreshTokenRequest("refresh"), null);

        verify(refreshTokenStore).revoke("refresh");
        verify(accessTokenBlacklist, never()).revoke(anyString());
    }

    @Test
    void logoutAlsoRevokesTheAccessTokenSentWithIt() {
        authService.logout(new RefreshTokenRequest("refresh"), "access");

        verify(refreshTokenStore).revoke("refresh");
        verify(accessTokenBlacklist).revoke("access");
    }

    /**
     * 계정이 없는 이메일도 공통 인증 실패 코드로 처리되는지 검증한다.
     */
    @Test
    void loginRejectsUnknownEmail() {
        when(userRepository.findByEmail("nobody@example.com")).thenReturn(Optional.empty());

        assertInvalidCredentials(new LoginRequest("nobody@example.com", "password1"));
    }

    /**
     * 기존 계정의 비밀번호 불일치가 공통 인증 실패 코드로 처리되는지 검증한다.
     */
    @Test
    void loginRejectsWrongPassword() {
        when(userRepository.findByEmail("fit@example.com")).thenReturn(Optional.of(storedUser(UserStatus.ACTIVE)));
        when(passwordEncoder.matches("wrong-password1", "ENCODED")).thenReturn(false);

        assertInvalidCredentials(new LoginRequest("fit@example.com", "wrong-password1"));
    }

    /**
     * 정지된 계정이 비밀번호 대조 이전에 인증에서 제외되는지 검증한다.
     */
    @Test
    void loginRejectsInactiveAccountEvenWithCorrectPassword() {
        when(userRepository.findByEmail("fit@example.com"))
                .thenReturn(Optional.of(storedUser(UserStatus.SUSPENDED)));

        assertInvalidCredentials(new LoginRequest("fit@example.com", "password1"));
    }

    /**
     * 인증 실패의 상세 원인 대신 INVALID_CREDENTIALS가 반환되는지 확인한다.
     */
    private void assertInvalidCredentials(LoginRequest request) {
        assertThatThrownBy(() -> authService.login(request))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_CREDENTIALS);
    }

    private void assertInvalidRefreshToken(String refreshToken) {
        assertThatThrownBy(() -> authService.reissue(new RefreshTokenRequest(refreshToken)))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_REFRESH_TOKEN);
    }

    /**
     * 지정된 상태와 ID를 가진 저장된 계정을 데이터베이스 없이 재현한다.
     */
    private User storedUser(UserStatus status) {
        User user = User.create("fit@example.com", "ENCODED", "fitzza");
        ReflectionTestUtils.setField(user, "id", 7L);
        ReflectionTestUtils.setField(user, "status", status);
        return user;
    }
}
