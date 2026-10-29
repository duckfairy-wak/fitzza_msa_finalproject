package com.fitzza.gateway.security;

import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * 토큰을 검증해 사용자 ID를 X-User-Id, 역할(USER·ADMIN)을 X-User-Role 헤더로 넘긴다. 뒤쪽 서비스는 이 헤더만 믿는다.
 *
 * <p>토큰이 없는 요청은 막지 않고 헤더 없이 넘긴다. 로그인이 필요한 API인지는 각 서비스가 판단하므로
 * 게이트웨이가 공개 API 목록을 따로 관리하지 않아도 된다.
 */
@Component
public class JwtAuthenticationFilter implements GlobalFilter, Ordered {

    static final String USER_ID_HEADER = "X-User-Id";
    static final String USER_ROLE_HEADER = "X-User-Role";
    static final String INTERNAL_TOKEN_HEADER = "X-Internal-Token";
    static final String SERVICE_TOKEN_HEADER = "X-Service-Token";
    private static final Logger log = LoggerFactory.getLogger(JwtAuthenticationFilter.class);
    private static final String BEARER_PREFIX = "Bearer ";
    private static final String AUTH_PATH_PREFIX = "/api/auth/";
    private static final String AUTH_V1_PATH_PREFIX = "/api/v1/auth/";

    private enum TokenStatus {
        ACTIVE,
        REVOKED,
        UNKNOWN
    }

    private final AccessTokenVerifier accessTokenVerifier;
    private final AccessTokenBlacklist accessTokenBlacklist;

    public JwtAuthenticationFilter(AccessTokenVerifier accessTokenVerifier, AccessTokenBlacklist accessTokenBlacklist) {
        this.accessTokenVerifier = accessTokenVerifier;
        this.accessTokenBlacklist = accessTokenBlacklist;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        ServerHttpRequest request = exchange.getRequest();
        // 회원가입·로그인·재발급·로그아웃은 만료된 토큰이 같이 실려 와도 통과해야 한다. 막으면 재발급을 못 한다.
        // FE는 /api/v1/auth/**, 스웨거는 /api/auth/** 를 쓴다.
        String path = request.getPath().value();
        if (path.startsWith(AUTH_PATH_PREFIX) || path.startsWith(AUTH_V1_PATH_PREFIX)) {
            return chain.filter(withUser(exchange, null));
        }
        // 토큰이 여러 개면 어느 것을 믿을지 정할 수 없으므로 거부한다.
        List<String> authorizations = request.getHeaders().getOrEmpty(HttpHeaders.AUTHORIZATION);
        if (authorizations.size() > 1) {
            return reject(exchange, HttpStatus.UNAUTHORIZED, "INVALID_TOKEN", "유효하지 않은 토큰입니다.");
        }
        String authorization = authorizations.isEmpty() ? null : authorizations.getFirst();
        // 인증 방식 이름(Bearer)은 대소문자를 구분하지 않는다.
        boolean hasBearerToken = authorization != null
                && authorization.regionMatches(true, 0, BEARER_PREFIX, 0, BEARER_PREFIX.length());
        if (!hasBearerToken) {
            return chain.filter(withUser(exchange, null));
        }

        String token = authorization.substring(BEARER_PREFIX.length()).trim();
        AccessTokenVerifier.VerifiedUser user;
        try {
            user = accessTokenVerifier.authenticate(token);
        } catch (ExpiredJwtException exception) {
            return reject(exchange, HttpStatus.UNAUTHORIZED, "TOKEN_EXPIRED", "토큰이 만료되었습니다.");
        } catch (JwtException | IllegalArgumentException exception) {
            return reject(exchange, HttpStatus.UNAUTHORIZED, "INVALID_TOKEN", "유효하지 않은 토큰입니다.");
        }

        ServerWebExchange authenticated = withUser(exchange, user);
        // 조회 오류는 여기서 상태로 바꿔 둔다. 뒤에서 잡으면 뒤쪽 서비스의 오류까지 인증 장애로 처리된다.
        return accessTokenBlacklist
                .isRevoked(token)
                .map(revoked -> revoked ? TokenStatus.REVOKED : TokenStatus.ACTIVE)
                .onErrorResume(exception -> {
                    log.warn("블랙리스트를 조회하지 못해 요청을 거부합니다: {}", exception.toString());
                    return Mono.just(TokenStatus.UNKNOWN);
                })
                .flatMap(status -> switch (status) {
                    case ACTIVE -> chain.filter(authenticated);
                    case REVOKED -> reject(exchange, HttpStatus.UNAUTHORIZED, "INVALID_TOKEN", "유효하지 않은 토큰입니다.");
                    // 확인하지 못한 토큰을 통과시키면 로그아웃한 토큰이 다시 쓰일 수 있어 막는다.
                    case UNKNOWN -> reject(
                            exchange,
                            HttpStatus.SERVICE_UNAVAILABLE,
                            "AUTH_UNAVAILABLE",
                            "인증 상태를 확인할 수 없습니다. 잠시 후 다시 시도해주세요.");
                });
    }

    // 라우팅보다 먼저 실행돼야 헤더가 뒤쪽 서비스로 전달된다.
    @Override
    public int getOrder() {
        return -1;
    }

    // 밖에서 보낸 X-User-Id·X-User-Role과 내부 호출 비밀 헤더는 항상 지운다.
    // 남겨 두면 헤더만으로 다른 사용자나 관리자 행세를 하거나 내부 API를 호출할 수 있다.
    private ServerWebExchange withUser(ServerWebExchange exchange, AccessTokenVerifier.VerifiedUser user) {
        ServerHttpRequest request = exchange.getRequest()
                .mutate()
                .headers(headers -> {
                    headers.remove(USER_ID_HEADER);
                    headers.remove(USER_ROLE_HEADER);
                    headers.remove(INTERNAL_TOKEN_HEADER);
                    headers.remove(SERVICE_TOKEN_HEADER);
                    if (user != null) {
                        headers.set(USER_ID_HEADER, String.valueOf(user.userId()));
                        headers.set(USER_ROLE_HEADER, user.role());
                    }
                })
                .build();
        return exchange.mutate().request(request).build();
    }

    // 프론트가 TOKEN_EXPIRED일 때만 재발급을 시도할 수 있도록 만료와 그 밖의 오류를 구분해 응답한다.
    private Mono<Void> reject(ServerWebExchange exchange, HttpStatus status, String code, String message) {
        ServerHttpResponse response = exchange.getResponse();
        response.setStatusCode(status);
        response.getHeaders().setContentType(MediaType.APPLICATION_JSON);
        String json = "{\"status\":" + status.value() + ",\"code\":\"" + code + "\",\"message\":\"" + message + "\"}";
        byte[] body = json.getBytes(StandardCharsets.UTF_8);
        return response.writeWith(Mono.just(response.bufferFactory().wrap(body)));
    }
}
