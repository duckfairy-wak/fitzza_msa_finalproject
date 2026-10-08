package com.fitzza.gateway.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jws;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Set;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.cloud.gateway.route.Route;
import org.springframework.cloud.gateway.support.ServerWebExchangeUtils;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

@Component
public class UserAuthenticationFilter implements GlobalFilter, Ordered {

    private static final String USER_ID_HEADER = "X-User-Id";
    private static final Set<String> PUBLIC_ENDPOINTS = Set.of(
            "POST /api/v1/auth/login",
            "POST /api/v1/auth/reissue",
            "POST /api/v1/auth/logout",
            "POST /api/v1/users/signup",
            "GET /api/v1/users/check-email",
            "GET /api/v1/users/check-nickname",
            "GET /api/v1/users/profile/options",
            "GET /api/v1/users/status");

    private final JwtParser jwtParser;

    public UserAuthenticationFilter(@Value("${jwt.secret}") String secret) {
        this.jwtParser = Jwts.parser()
                .verifyWith(Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8)))
                .build();
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        ServerHttpRequest.Builder request = exchange.getRequest().mutate()
                .headers(headers -> headers.remove(USER_ID_HEADER));
        Route route = exchange.getAttribute(ServerWebExchangeUtils.GATEWAY_ROUTE_ATTR);
        String endpoint = exchange.getRequest().getMethod() + " "
                + exchange.getRequest().getPath().value();

        // Protect the entire user route so new user endpoints are authenticated by default.
        if (route != null && "user-service".equals(route.getId()) && !PUBLIC_ENDPOINTS.contains(endpoint)) {
            String userId;
            try {
                userId = authenticatedUserId(exchange.getRequest().getHeaders());
            } catch (JwtException | IllegalArgumentException exception) {
                exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
                exchange.getResponse().getHeaders().set(HttpHeaders.WWW_AUTHENTICATE, "Bearer");
                return exchange.getResponse().setComplete();
            }
            request.headers(headers -> headers.set(USER_ID_HEADER, userId));
        }
        return chain.filter(exchange.mutate().request(request.build()).build());
    }

    private String authenticatedUserId(HttpHeaders headers) {
        List<String> authorization = headers.getOrEmpty(HttpHeaders.AUTHORIZATION);
        if (authorization.size() != 1 || !authorization.getFirst().regionMatches(true, 0, "Bearer ", 0, 7)) {
            throw new IllegalArgumentException("A single Bearer token is required.");
        }
        Jws<Claims> token = jwtParser.parseSignedClaims(authorization.getFirst().substring(7));
        if (!Jwts.SIG.HS256.getId().equals(token.getHeader().getAlgorithm())) {
            throw new IllegalArgumentException("HS256 is required.");
        }
        Claims claims = token.getPayload();
        long userId = Long.parseLong(claims.getSubject());
        if (claims.getExpiration() == null || userId <= 0) {
            throw new IllegalArgumentException("An expiration and a positive user ID are required.");
        }
        return Long.toString(userId);
    }

    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE;
    }
}
