package com.fitzza.user.service;

import com.fitzza.user.domain.User;
import com.fitzza.user.domain.UserBody;
import com.fitzza.user.dto.SignupRequest;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.repository.UserBodyRepository;
import com.fitzza.user.repository.UserRepository;
import java.util.regex.Pattern;
import org.hibernate.exception.ConstraintViolationException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class UserService {

    private static final Pattern EMAIL_PATTERN = Pattern.compile(User.EMAIL_REGEX);
    private static final Pattern NICKNAME_PATTERN = Pattern.compile(User.NICKNAME_REGEX);

    private final UserRepository userRepository;
    private final UserBodyRepository userBodyRepository;
    private final PasswordEncoder passwordEncoder;

    /**
     * 사용자와 신체 프로필 저장 및 비밀번호 해싱에 사용할 의존성을 주입한다.
     */
    public UserService(
            UserRepository userRepository,
            UserBodyRepository userBodyRepository,
            PasswordEncoder passwordEncoder) {
        this.userRepository = userRepository;
        this.userBodyRepository = userBodyRepository;
        this.passwordEncoder = passwordEncoder;
    }

    /**
     * 검증된 가입 정보로 사용자와 빈 신체 프로필을 하나의 트랜잭션에서 저장한다.
     * 이메일은 정규화하고 비밀번호는 인코딩한 뒤 저장한다.
     *
     * @param request 컨트롤러에서 형식 검증을 마친 가입 정보
     * @return 생성된 사용자 ID
     * @throws UserApiException 이메일 또는 닉네임 중복이 확인된 경우
     * @throws DataIntegrityViolationException 계정 중복 이외의 무결성 제약을 위반한 경우
     */
    @Transactional
    public Long signUp(SignupRequest request) {
        String email = User.normalizeEmail(request.email());
        if (userRepository.existsByEmail(email)) {
            throw new UserApiException(ErrorCode.DUPLICATE_EMAIL);
        }
        if (userRepository.existsByNickname(request.nickname())) {
            throw new UserApiException(ErrorCode.DUPLICATE_NICKNAME);
        }

        User user = saveUser(User.create(email, passwordEncoder.encode(request.password()), request.nickname()));
        userBodyRepository.save(UserBody.emptyFor(user.getId()));
        return user.getId();
    }

    /**
     * 이메일을 정규화하고 형식을 검사한 뒤 현재 사용 가능 여부를 확인한다.
     * 조회 결과는 예약을 보장하지 않으므로 가입 시 중복 여부를 다시 확인한다.
     *
     * @param email 사용 가능 여부를 확인할 이메일
     * @return 같은 이메일의 계정이 없으면 true
     * @throws UserApiException 입력이 비어 있거나 이메일 형식이 잘못된 경우
     */
    @Transactional(readOnly = true)
    public boolean isEmailAvailable(String email) {
        requireText(email);
        String normalizedEmail = User.normalizeEmail(email);
        if (!EMAIL_PATTERN.matcher(normalizedEmail).matches()) {
            throw new UserApiException(ErrorCode.INVALID_INPUT);
        }
        return !userRepository.existsByEmail(normalizedEmail);
    }

    /**
     * 닉네임 형식을 검사한 뒤 현재 사용 가능 여부를 확인한다.
     * 조회 결과는 예약을 보장하지 않으므로 가입 시 중복 여부를 다시 확인한다.
     *
     * @param nickname 사용 가능 여부를 확인할 닉네임
     * @return 같은 닉네임의 계정이 없으면 true
     * @throws UserApiException 입력이 비어 있거나 닉네임 형식이 잘못된 경우
     */
    @Transactional(readOnly = true)
    public boolean isNicknameAvailable(String nickname) {
        requireText(nickname);
        if (!NICKNAME_PATTERN.matcher(nickname).matches()) {
            throw new UserApiException(ErrorCode.INVALID_INPUT);
        }
        return !userRepository.existsByNickname(nickname);
    }

    /**
     * 저장 내용을 즉시 반영해 동시 가입으로 발생한 이메일·닉네임 고유 제약 위반을 변환한다.
     * 알 수 없는 제약이나 다른 무결성 오류는 원래 예외를 유지한다.
     *
     * @param user 저장할 사용자
     * @return 저장된 사용자
     * @throws UserApiException 알려진 계정 고유 제약을 위반한 경우
     * @throws DataIntegrityViolationException 그 외 무결성 오류가 발생한 경우
     */
    private User saveUser(User user) {
        try {
            return userRepository.saveAndFlush(user);
        } catch (DataIntegrityViolationException exception) {
            for (Throwable cause = exception.getCause(); cause != null; cause = cause.getCause()) {
                if (cause instanceof ConstraintViolationException violation
                        && (User.EMAIL_UNIQUE_CONSTRAINT.equals(violation.getConstraintName())
                        || User.NICKNAME_UNIQUE_CONSTRAINT.equals(violation.getConstraintName()))) {
                    throw new UserApiException(ErrorCode.DUPLICATE_ACCOUNT);
                }
            }
            throw exception;
        }
    }

    /**
     * null 또는 공백뿐인 값을 INVALID_INPUT 오류로 거부한다.
     */
    private void requireText(String value) {
        if (value == null || value.isBlank()) {
            throw new UserApiException(ErrorCode.INVALID_INPUT);
        }
    }
}
