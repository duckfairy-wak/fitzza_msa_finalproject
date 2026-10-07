package com.fitzza.user.service;

import com.fitzza.user.domain.User;
import com.fitzza.user.domain.UserBody;
import com.fitzza.user.dto.SignupRequest;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.repository.UserBodyRepository;
import com.fitzza.user.repository.UserRepository;
import java.util.regex.Pattern;
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

    public UserService(
            UserRepository userRepository,
            UserBodyRepository userBodyRepository,
            PasswordEncoder passwordEncoder) {
        this.userRepository = userRepository;
        this.userBodyRepository = userBodyRepository;
        this.passwordEncoder = passwordEncoder;
    }

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

    @Transactional(readOnly = true)
    public boolean isEmailAvailable(String email) {
        requireText(email);
        String normalizedEmail = User.normalizeEmail(email);
        if (!EMAIL_PATTERN.matcher(normalizedEmail).matches()) {
            throw new UserApiException(ErrorCode.INVALID_INPUT);
        }
        return !userRepository.existsByEmail(normalizedEmail);
    }

    @Transactional(readOnly = true)
    public boolean isNicknameAvailable(String nickname) {
        requireText(nickname);
        if (!NICKNAME_PATTERN.matcher(nickname).matches()) {
            throw new UserApiException(ErrorCode.INVALID_INPUT);
        }
        return !userRepository.existsByNickname(nickname);
    }

    // 중복 확인을 통과한 뒤 같은 값으로 동시에 가입한 요청은 DB 유니크 제약에서 걸린다.
    private User saveUser(User user) {
        try {
            return userRepository.saveAndFlush(user);
        } catch (DataIntegrityViolationException exception) {
            throw new UserApiException(ErrorCode.DUPLICATE_ACCOUNT);
        }
    }

    private void requireText(String value) {
        if (value == null || value.isBlank()) {
            throw new UserApiException(ErrorCode.INVALID_INPUT);
        }
    }
}
