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

    /**
     * 모의 저장소와 인코더로 가입 서비스의 저장 및 오류 처리 흐름을 검증할 준비를 한다.
     */
    @BeforeEach
    void setUp() {
        userService = new UserService(userRepository, userBodyRepository, passwordEncoder);
    }

    /**
     * 가입 시 이메일 정규화·비밀번호 해싱·활성 상태 및 같은 ID의 빈 프로필 저장을 검증한다.
     */
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

    /**
     * 이메일 중복이 감지되면 사용자 저장 전에 구체적인 중복 오류를 반환하는지 검증한다.
     */
    @Test
    void signUpRejectsDuplicateEmail() {
        when(userRepository.existsByEmail("fit@example.com")).thenReturn(true);

        assertThatThrownBy(() -> userService.signUp(REQUEST))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.DUPLICATE_EMAIL);
        verify(userRepository, never()).saveAndFlush(any(User.class));
    }

    /**
     * 닉네임 중복이 감지되면 사용자 저장 전에 구체적인 중복 오류를 반환하는지 검증한다.
     */
    @Test
    void signUpRejectsDuplicateNickname() {
        when(userRepository.existsByNickname("fitzza")).thenReturn(true);

        assertThatThrownBy(() -> userService.signUp(REQUEST))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.DUPLICATE_NICKNAME);
        verify(userRepository, never()).saveAndFlush(any(User.class));
    }

    /**
     * 중첩된 알려진 고유 제약 위반을 계정 중복으로 변환하고 프로필 저장을 중단하는지 검증한다.
     */
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

    /**
     * 알 수 없거나 계정 중복과 무관한 제약 위반의 원래 예외가 유지되는지 검증한다.
     */
    @ParameterizedTest
    @NullSource
    @ValueSource(strings = {"users_pkey", "fk_users_account", "users_status_check", "uk_users_email_other"})
    void signUpRethrowsUnrelatedOrUnknownConstraintViolations(String constraintName) {
        DataIntegrityViolationException exception = new DataIntegrityViolationException("integrity violation",
                new ConstraintViolationException("integrity violation", new SQLException(), constraintName));
        assertSignUpRethrows(exception);
    }

    /**
     * 원인 예외가 없을 때 메시지만으로 계정 중복을 추정하지 않는지 검증한다.
     */
    @Test
    void signUpRethrowsIntegrityViolationWithoutCause() {
        assertSignUpRethrows(new DataIntegrityViolationException("duplicate key"));
    }

    /**
     * 메시지에 계정 제약 이름이 있어도 다른 종류의 원인을 중복으로 변환하지 않는지 검증한다.
     */
    @Test
    void signUpRethrowsOtherIntegrityCausesEvenWhenMessageMentionsAccountConstraint() {
        assertSignUpRethrows(new DataIntegrityViolationException("integrity violation",
                new SQLException("uk_users_email", "23502")));
    }

    /**
     * 원래 무결성 예외가 그대로 전달되고 프로필이 저장되지 않는지 확인한다.
     */
    private void assertSignUpRethrows(DataIntegrityViolationException exception) {
        when(passwordEncoder.encode("password1")).thenReturn("ENCODED");
        when(userRepository.saveAndFlush(any(User.class))).thenThrow(exception);

        assertThatThrownBy(() -> userService.signUp(REQUEST)).isSameAs(exception);
        verify(userBodyRepository, never()).save(any(UserBody.class));
    }

    /**
     * 중복 조회에서도 가입과 같은 이메일 정규화 규칙이 적용되는지 검증한다.
     */
    @Test
    void emailIsAvailableOnlyWhenNoUserHasTheNormalizedEmail() {
        when(userRepository.existsByEmail("fit@example.com")).thenReturn(true);
        when(userRepository.existsByEmail("new@example.com")).thenReturn(false);

        assertThat(userService.isEmailAvailable(" FIT@example.com")).isFalse();
        assertThat(userService.isEmailAvailable("new@example.com")).isTrue();
    }

    /**
     * 잘못된 이메일 형식의 중복 조회가 INVALID_INPUT으로 거부되는지 검증한다.
     */
    @Test
    void emailAvailabilityCheckRejectsMalformedEmail() {
        assertThatThrownBy(() -> userService.isEmailAvailable("fit@example"))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_INPUT);
    }

    /**
     * 닉네임 존재 여부의 반대 값이 사용 가능 여부로 반환되는지 검증한다.
     */
    @Test
    void nicknameIsAvailableOnlyWhenNoUserHasIt() {
        when(userRepository.existsByNickname("fitzza")).thenReturn(true);
        when(userRepository.existsByNickname("newbie")).thenReturn(false);

        assertThat(userService.isNicknameAvailable("fitzza")).isFalse();
        assertThat(userService.isNicknameAvailable("newbie")).isTrue();
    }

    /**
     * 닉네임 중복 조회에도 특수문자 금지 규칙이 적용되는지 검증한다.
     */
    @Test
    void nicknameAvailabilityCheckRejectsSpecialCharacter() {
        assertThatThrownBy(() -> userService.isNicknameAvailable("fit_zza"))
                .isInstanceOf(UserApiException.class)
                .extracting("errorCode")
                .isEqualTo(ErrorCode.INVALID_INPUT);
    }

    /**
     * 공백 이메일과 빈 닉네임이 사용 가능 여부 조회에서 거부되는지 검증한다.
     */
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
