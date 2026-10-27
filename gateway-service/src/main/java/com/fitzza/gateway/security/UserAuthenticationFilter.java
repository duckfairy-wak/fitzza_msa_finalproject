package com.fitzza.gateway.security;

import java.nio.charset.StandardCharsets;
import java.util.Set;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.cloud.gateway.route.Route;
import org.springframework.cloud.gateway.support.ServerWebExchangeUtils;
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
 * 로그인 필수 라우트(user-service, recommendation-service, order-service-orders)는 공개 목록에 없는
 * 주소를 모두 로그인 필수로 둔다. 새 주소가 생겨도 기본으로 보호된다. 추천은 2026-10-14 회의에서
 * 회원만 쓰기로 정했다.
 *
 * <p>토큰 검증은 {@link JwtAuthenticationFilter}가 먼저 끝낸다. 만료·위조·로그아웃된 토큰은 거기서 코드와 함께
 * 거부되므로, 여기서는 검증된 사용자 헤더가 붙었는지만 본다.
 */
@Component
public class UserAuthenticationFilter implements GlobalFilter, Ordered {

    private static final Set<String> LOGIN_REQUIRED_ROUTE_IDS =
            Set.of("user-service", "recommendation-service", "order-service-orders");
    private static final Set<String> PUBLIC_ENDPOINTS = Set.of(
            "POST /api/auth/signin",
            "POST /api/auth/refresh",
            "POST /api/auth/signout",
            "POST /api/auth/signup",
            "GET /api/users/preferences/fits",
            "GET /api/users/preferences/styles");
    private static final byte[] UNAUTHENTICATED_BODY =
            "{\"status\":401,\"code\":\"UNAUTHENTICATED\",\"message\":\"로그인이 필요합니다.\"}".getBytes(StandardCharsets.UTF_8);

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        Route route = exchange.getAttribute(ServerWebExchangeUtils.GATEWAY_ROUTE_ATTR);
        ServerHttpRequest request = exchange.getRequest();
        // FE의 /api/v1/** 와 스웨거의 /api/** 를 같은 공개 API 목록으로 본다.
        String endpoint = request.getMethod() + " " + withoutApiVersion(request.getPath().value());
        boolean protectedUserEndpoint =
                route != null && LOGIN_REQUIRED_ROUTE_IDS.contains(route.getId()) && !PUBLIC_ENDPOINTS.contains(endpoint);
        if (!protectedUserEndpoint || request.getHeaders().containsKey(JwtAuthenticationFilter.USER_ID_HEADER)) {
            return chain.filter(exchange);
        }
        return rejectUnauthenticated(exchange.getResponse());
    }

    private Mono<Void> rejectUnauthenticated(ServerHttpResponse response) {
        response.setStatusCode(HttpStatus.UNAUTHORIZED);
        response.getHeaders().set(HttpHeaders.WWW_AUTHENTICATE, "Bearer");
        response.getHeaders().setContentType(MediaType.APPLICATION_JSON);
        return response.writeWith(Mono.just(response.bufferFactory().wrap(UNAUTHENTICATED_BODY)));
    }

    // JwtAuthenticationFilter(-1)가 사용자 헤더를 정리하고 다시 붙인 뒤에 돌아야 한다.
    @Override
    public int getOrder() {
        return 0;
    }

    private static String withoutApiVersion(String path) {
        if (path.startsWith("/api/v1/")) {
            return "/api/" + path.substring("/api/v1/".length());
        }
        return path;
    }
}
