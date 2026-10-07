package com.fitzza.user.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

import com.fitzza.user.domain.User;
import com.fitzza.user.domain.UserStatus;
import com.fitzza.user.dto.LoginRequest;
import com.fitzza.user.dto.LoginResponse;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.repository.UserRepository;
import com.fitzza.user.security.JwtTokenProvider;
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

    private AuthService authService;

    @BeforeEach
    void setUp() {
        authService = new AuthService(userRepository, passwordEncoder, jwtTokenProvider);
    }

    @Test
    void loginReturnsTokenAndUserInfoForMatchingCredentials() {
        User user = storedUser(UserStatus.ACTIVE);
        when(userRepository.findByEmail("fit@example.com")).thenReturn(Optional.of(user));
        when(passwordEncoder.matches("password1", "ENCODED")).thenReturn(true);
        when(jwtTokenProvider.createAccessToken(7L)).thenReturn("token");

        LoginResponse response = authService.login(new LoginRequest(" Fit@Example.com", "password1"));

        assertThat(response).isEqualTo(new LoginResponse("token", 7L, "fitzza"));
    }

    @Test
    void loginRejectsUnknownEmail() {
        when(userRepository.findByEmail("nobody@example.com")).thenReturn(Optional.empty());

        assertInvalidCredentials(new LoginRequest("nobody@example.com", "password1"));
    }

    @Test
    void loginRejectsWrongPassword() {
        when(userRepository.findByEmail("fit@example.com")).thenReturn(Optional.of(storedUser(UserStatus.ACTIVE)));
        when(passwordEncoder.matches("wrong-password1", "ENCODED")).thenReturn(false);

        assertInvalidCredentials(new LoginRequest("fit@example.com", "wrong-password1"));
    }

    @Test
    void loginRejectsInactiveAccountEvenWithCorrectPassword() {
        when(userRepository.findByEmail("fit@example.com"))
                .thenReturn(Optional.of(storedUser(UserStatus.SUSPENDED)));

        assertInvalidCredentials(new LoginRequest("fit@example.com", "password1"));
    }

    private void assertInvalidCredentials(LoginRequest request) {
        assertThatThrownBy(() -> authService.login(request))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_CREDENTIALS);
    }

    private User storedUser(UserStatus status) {
        User user = User.create("fit@example.com", "ENCODED", "fitzza");
        ReflectionTestUtils.setField(user, "id", 7L);
        ReflectionTestUtils.setField(user, "status", status);
        return user;
    }
}
