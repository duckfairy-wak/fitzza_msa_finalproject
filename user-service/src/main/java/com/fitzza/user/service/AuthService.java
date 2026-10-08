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

    /**
     * 계정 조회, 비밀번호 대조 및 토큰 발급에 사용할 의존성을 주입한다.
     */
    public AuthService(
            UserRepository userRepository,
            PasswordEncoder passwordEncoder,
            JwtTokenProvider jwtTokenProvider) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.jwtTokenProvider = jwtTokenProvider;
    }

    /**
     * 정규화된 이메일로 활성 계정을 인증하고 토큰과 사용자 정보를 반환한다.
     * 계정 부재, 비활성 상태, 비밀번호 불일치는 원인을 구분하지 않는 같은 오류로 처리한다.
     *
     * @param request null이 아닌 이메일과 비밀번호를 포함한 검증된 요청
     * @return 액세스 토큰, 사용자 ID 및 닉네임
     * @throws UserApiException 인증 조건을 충족하지 못한 경우
     */
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
