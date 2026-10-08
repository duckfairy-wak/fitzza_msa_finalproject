package com.fitzza.user.service;

import com.fitzza.user.domain.User;
import com.fitzza.user.dto.LoginRequest;
import com.fitzza.user.dto.LoginResponse;
import com.fitzza.user.dto.RefreshTokenRequest;
import com.fitzza.user.dto.TokenResponse;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import com.fitzza.user.repository.UserRepository;
import com.fitzza.user.security.JwtTokenProvider;
import com.fitzza.user.security.RefreshTokenStore;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenProvider jwtTokenProvider;
    private final RefreshTokenStore refreshTokenStore;

    /**
     * 계정 조회, 비밀번호 대조 및 토큰 발급에 사용할 의존성을 주입한다.
     */
    public AuthService(
            UserRepository userRepository,
            PasswordEncoder passwordEncoder,
            JwtTokenProvider jwtTokenProvider,
            RefreshTokenStore refreshTokenStore) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.jwtTokenProvider = jwtTokenProvider;
        this.refreshTokenStore = refreshTokenStore;
    }

    /**
     * 정규화된 이메일로 활성 계정을 인증하고 토큰과 사용자 정보를 반환한다.
     * 계정 부재, 비활성 상태, 비밀번호 불일치는 원인을 구분하지 않는 같은 오류로 처리한다.
     *
     * @param request null이 아닌 이메일과 비밀번호를 포함한 검증된 요청
     * @return 액세스 토큰, 리프레시 토큰, 사용자 ID 및 닉네임
     * @throws UserApiException 인증 조건을 충족하지 못한 경우
     */
    @Transactional(readOnly = true)
    public LoginResponse login(LoginRequest request) {
        User user = userRepository.findByEmail(User.normalizeEmail(request.email()))
                .filter(User::isActive)
                .filter(found -> passwordEncoder.matches(request.password(), found.getPassword()))
                .orElseThrow(() -> new UserApiException(ErrorCode.INVALID_CREDENTIALS));

        return new LoginResponse(
                jwtTokenProvider.createAccessToken(user.getId()),
                refreshTokenStore.issue(user.getId()),
                user.getId(),
                user.getNickname());
    }

    // 쓴 Refresh Token은 바로 폐기하고 새것을 준다. 탈취된 토큰이 한 번 쓰이면 원래 주인의 재발급이 실패해 드러난다.
    @Transactional(readOnly = true)
    public TokenResponse reissue(RefreshTokenRequest request) {
        Long userId = refreshTokenStore
                .consume(request.refreshToken())
                .orElseThrow(() -> new UserApiException(ErrorCode.INVALID_REFRESH_TOKEN));
        // 로그인 이후 정지되거나 탈퇴한 계정에는 새 토큰을 주지 않는다.
        userRepository
                .findById(userId)
                .filter(User::isActive)
                .orElseThrow(() -> new UserApiException(ErrorCode.INVALID_REFRESH_TOKEN));

        return new TokenResponse(jwtTokenProvider.createAccessToken(userId), refreshTokenStore.issue(userId));
    }

    // 이미 지워졌거나 모르는 토큰이어도 결과는 같다(다시 요청해도 성공).
    public void logout(RefreshTokenRequest request) {
        refreshTokenStore.revoke(request.refreshToken());
    }
}
