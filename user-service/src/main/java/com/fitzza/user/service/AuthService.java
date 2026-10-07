package com.fitzza.user.service;

import com.fitzza.user.domain.User;
import com.fitzza.user.dto.LoginRequest;
import com.fitzza.user.dto.LoginResponse;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.repository.UserRepository;
import com.fitzza.user.security.JwtTokenProvider;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenProvider jwtTokenProvider;

    public AuthService(
            UserRepository userRepository,
            PasswordEncoder passwordEncoder,
            JwtTokenProvider jwtTokenProvider) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.jwtTokenProvider = jwtTokenProvider;
    }

    // 어떤 조건에서 실패했는지 드러나지 않도록 모든 실패를 같은 오류로 응답한다.
    @Transactional(readOnly = true)
    public LoginResponse login(LoginRequest request) {
        User user = userRepository.findByEmail(User.normalizeEmail(request.email()))
                .filter(User::isActive)
                .filter(found -> passwordEncoder.matches(request.password(), found.getPassword()))
                .orElseThrow(() -> new UserApiException(ErrorCode.INVALID_CREDENTIALS));

        String accessToken = jwtTokenProvider.createAccessToken(user.getId());
        return new LoginResponse(accessToken, user.getId(), user.getNickname());
    }
}
