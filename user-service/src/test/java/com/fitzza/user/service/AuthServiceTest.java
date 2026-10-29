package com.fitzza.user.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fitzza.user.domain.User;
import com.fitzza.user.domain.UserRole;
import com.fitzza.user.domain.UserStatus;
import com.fitzza.user.dto.LoginRequest;
import com.fitzza.user.dto.RefreshTokenRequest;
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

    private static final String DUMMY_HASH = "DUMMY_HASH";

    private AuthService authService;

    /**
     * 모의 의존성을 주입해 외부 저장소와 독립적으로 인증 서비스를 검증한다.
     */
    @BeforeEach
    void setUp() {
        when(passwordEncoder.encode(anyString())).thenReturn(DUMMY_HASH);
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
        when(jwtTokenProvider.createAccessToken(7L, UserRole.USER)).thenReturn("access");
        when(refreshTokenStore.issue(7L)).thenReturn("refresh");

        LoginResult response = authService.login(new LoginRequest(" Fit@Example.com", "password1"));

        assertThat(response).isEqualTo(new LoginResult("access", "refresh", 7L, "fitzza", UserRole.USER));
    }

    @Test
    void failedLoginIssuesNoRefreshToken() {
        when(userRepository.findByEmail("fit@example.com")).thenReturn(Optional.of(storedUser(UserStatus.ACTIVE)));
        when(passwordEncoder.matches("wrong-password1", "ENCODED")).thenReturn(false);

        assertInvalidCredentials(new LoginRequest("fit@example.com", "wrong-password1"));
        verify(refreshTokenStore, never()).issue(anyLong());
    }

    // 관리자는 토큰과 응답에 ADMIN 역할이 실린다. 게이트웨이가 토큰의 역할을 X-User-Role로 넘긴다.
    @Test
    void loginCarriesTheAdminRoleIntoTheTokenAndResponse() {
        User admin = storedUser(UserStatus.ACTIVE);
        ReflectionTestUtils.setField(admin, "role", UserRole.ADMIN);
        when(userRepository.findByEmail("fit@example.com")).thenReturn(Optional.of(admin));
        when(passwordEncoder.matches("password1", "ENCODED")).thenReturn(true);
        when(jwtTokenProvider.createAccessToken(7L, UserRole.ADMIN)).thenReturn("admin-access");
        when(refreshTokenStore.issue(7L)).thenReturn("refresh");

        LoginResult response = authService.login(new LoginRequest("fit@example.com", "password1"));

        assertThat(response).isEqualTo(new LoginResult("admin-access", "refresh", 7L, "fitzza", UserRole.ADMIN));
    }

    // 재발급할 때 역할을 DB에서 다시 읽으므로, 역할이 바뀌면 다음 재발급부터 반영된다.
    @Test
    void reissueUsesTheCurrentRoleFromTheDatabase() {
        User admin = storedUser(UserStatus.ACTIVE);
        ReflectionTestUtils.setField(admin, "role", UserRole.ADMIN);
        when(refreshTokenStore.consume("old-refresh")).thenReturn(Optional.of(7L));
        when(userRepository.findById(7L)).thenReturn(Optional.of(admin));
        when(jwtTokenProvider.createAccessToken(7L, UserRole.ADMIN)).thenReturn("admin-access");
        when(refreshTokenStore.issue(7L)).thenReturn("new-refresh");

        assertThat(authService.reissue(new RefreshTokenRequest("old-refresh")))
                .isEqualTo(new TokenResult("admin-access", "new-refresh"));
    }

    @Test
    void reissueSwapsTheUsedRefreshTokenForANewPair() {
        when(refreshTokenStore.consume("old-refresh")).thenReturn(Optional.of(7L));
        when(userRepository.findById(7L)).thenReturn(Optional.of(storedUser(UserStatus.ACTIVE)));
        when(jwtTokenProvider.createAccessToken(7L, UserRole.USER)).thenReturn("new-access");
        when(refreshTokenStore.issue(7L)).thenReturn("new-refresh");

        TokenResult response = authService.reissue(new RefreshTokenRequest("old-refresh"));

        assertThat(response).isEqualTo(new TokenResult("new-access", "new-refresh"));
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
     * 없는 이메일도 비밀번호 대조를 한 번 거쳐, 응답 시간으로 가입 여부가 드러나지 않는지 검증한다.
     */
    @Test
    void loginComparesAPasswordEvenWhenTheEmailIsUnknown() {
        when(userRepository.findByEmail("nobody@example.com")).thenReturn(Optional.empty());

        assertInvalidCredentials(new LoginRequest("nobody@example.com", "password1"));

        verify(passwordEncoder).matches("password1", DUMMY_HASH);
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
     * 정지된 계정은 비밀번호가 맞아도 인증에서 제외되는지 검증한다.
     */
    @Test
    void loginRejectsInactiveAccountEvenWithCorrectPassword() {
        when(userRepository.findByEmail("fit@example.com"))
                .thenReturn(Optional.of(storedUser(UserStatus.SUSPENDED)));
        when(passwordEncoder.matches("password1", "ENCODED")).thenReturn(true);

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
