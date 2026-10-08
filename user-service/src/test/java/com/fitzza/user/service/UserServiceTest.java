package com.fitzza.user.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fitzza.user.domain.User;
import com.fitzza.user.domain.UserBody;
import com.fitzza.user.dto.SignupRequest;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.repository.UserBodyRepository;
import com.fitzza.user.repository.UserRepository;
import java.sql.SQLException;
import org.hibernate.exception.ConstraintViolationException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.util.ReflectionTestUtils;

@ExtendWith(MockitoExtension.class)
class UserServiceTest {

    private static final SignupRequest REQUEST = new SignupRequest(" Fit@Example.com ", "password1", "fitzza");

    @Mock
    private UserRepository userRepository;

    @Mock
    private UserBodyRepository userBodyRepository;

    @Mock
    private PasswordEncoder passwordEncoder;

    private UserService userService;

    @BeforeEach
    void setUp() {
        userService = new UserService(userRepository, userBodyRepository, passwordEncoder);
    }

    @Test
    void signUpStoresNormalizedEmailEncodedPasswordAndEmptyBodyRow() {
        when(passwordEncoder.encode("password1")).thenReturn("ENCODED");
        when(userRepository.saveAndFlush(any(User.class))).thenAnswer(invocation -> {
            User user = invocation.getArgument(0);
            ReflectionTestUtils.setField(user, "id", 7L);
            return user;
        });

        Long userId = userService.signUp(REQUEST);

        ArgumentCaptor<User> savedUser = ArgumentCaptor.forClass(User.class);
        ArgumentCaptor<UserBody> savedBody = ArgumentCaptor.forClass(UserBody.class);
        verify(userRepository).saveAndFlush(savedUser.capture());
        verify(userBodyRepository).save(savedBody.capture());
        assertThat(userId).isEqualTo(7L);
        assertThat(savedUser.getValue().getEmail()).isEqualTo("fit@example.com");
        assertThat(savedUser.getValue().getPassword()).isEqualTo("ENCODED");
        assertThat(savedUser.getValue().getNickname()).isEqualTo("fitzza");
        assertThat(savedUser.getValue().isActive()).isTrue();
        assertThat(savedBody.getValue().getUserId()).isEqualTo(7L);
    }

    @Test
    void signUpRejectsDuplicateEmail() {
        when(userRepository.existsByEmail("fit@example.com")).thenReturn(true);

        assertThatThrownBy(() -> userService.signUp(REQUEST))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.DUPLICATE_EMAIL);
        verify(userRepository, never()).saveAndFlush(any(User.class));
    }

    @Test
    void signUpRejectsDuplicateNickname() {
        when(userRepository.existsByNickname("fitzza")).thenReturn(true);

        assertThatThrownBy(() -> userService.signUp(REQUEST))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.DUPLICATE_NICKNAME);
        verify(userRepository, never()).saveAndFlush(any(User.class));
    }

    @ParameterizedTest
    @ValueSource(strings = {"uk_users_email", "uk_users_nickname"})
    void signUpReportsConflictWhenUniqueConstraintFailsOnConcurrentRequest(String constraintName) {
        when(passwordEncoder.encode("password1")).thenReturn("ENCODED");
        when(userRepository.saveAndFlush(any(User.class)))
                .thenThrow(new DataIntegrityViolationException("duplicate key",
                        new RuntimeException(new ConstraintViolationException(
                                "duplicate key", new SQLException("duplicate key", "23505"), constraintName))));

        assertThatThrownBy(() -> userService.signUp(REQUEST))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.DUPLICATE_ACCOUNT);
        verify(userBodyRepository, never()).save(any(UserBody.class));
    }

    @ParameterizedTest
    @NullSource
    @ValueSource(strings = {"users_pkey", "fk_users_account", "users_status_check", "uk_users_email_other"})
    void signUpRethrowsUnrelatedOrUnknownConstraintViolations(String constraintName) {
        DataIntegrityViolationException exception = new DataIntegrityViolationException("integrity violation",
                new ConstraintViolationException("integrity violation", new SQLException(), constraintName));
        assertSignUpRethrows(exception);
    }

    @Test
    void signUpRethrowsIntegrityViolationWithoutCause() {
        assertSignUpRethrows(new DataIntegrityViolationException("duplicate key"));
    }

    @Test
    void signUpRethrowsOtherIntegrityCausesEvenWhenMessageMentionsAccountConstraint() {
        assertSignUpRethrows(new DataIntegrityViolationException("integrity violation",
                new SQLException("uk_users_email", "23502")));
    }

    private void assertSignUpRethrows(DataIntegrityViolationException exception) {
        when(passwordEncoder.encode("password1")).thenReturn("ENCODED");
        when(userRepository.saveAndFlush(any(User.class))).thenThrow(exception);

        assertThatThrownBy(() -> userService.signUp(REQUEST)).isSameAs(exception);
        verify(userBodyRepository, never()).save(any(UserBody.class));
    }

    @Test
    void emailIsAvailableOnlyWhenNoUserHasTheNormalizedEmail() {
        when(userRepository.existsByEmail("fit@example.com")).thenReturn(true);
        when(userRepository.existsByEmail("new@example.com")).thenReturn(false);

        assertThat(userService.isEmailAvailable(" FIT@example.com")).isFalse();
        assertThat(userService.isEmailAvailable("new@example.com")).isTrue();
    }

    @Test
    void emailAvailabilityCheckRejectsMalformedEmail() {
        assertThatThrownBy(() -> userService.isEmailAvailable("fit@example"))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_INPUT);
    }

    @Test
    void nicknameIsAvailableOnlyWhenNoUserHasIt() {
        when(userRepository.existsByNickname("fitzza")).thenReturn(true);
        when(userRepository.existsByNickname("newbie")).thenReturn(false);

        assertThat(userService.isNicknameAvailable("fitzza")).isFalse();
        assertThat(userService.isNicknameAvailable("newbie")).isTrue();
    }

    @Test
    void nicknameAvailabilityCheckRejectsSpecialCharacter() {
        assertThatThrownBy(() -> userService.isNicknameAvailable("fit_zza"))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_INPUT);
    }

    @Test
    void availabilityCheckRejectsBlankValue() {
        assertThatThrownBy(() -> userService.isEmailAvailable(" "))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_INPUT);
        assertThatThrownBy(() -> userService.isNicknameAvailable(""))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_INPUT);
    }
}
