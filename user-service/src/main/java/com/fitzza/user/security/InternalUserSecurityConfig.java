package com.fitzza.user.security;

import com.fitzza.user.controller.InternalUserController;
import com.fitzza.user.exception.ErrorCode;
import com.fitzza.user.exception.UserApiException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class InternalUserSecurityConfig implements WebMvcConfigurer {

    private final byte[] internalCallToken;

    public InternalUserSecurityConfig(@Value("${internal.call-token}") String internalCallToken) {
        if (internalCallToken == null || internalCallToken.isBlank()) {
            throw new IllegalArgumentException("INTERNAL_CALL_TOKEN must be set and non-blank");
        }
        this.internalCallToken = internalCallToken.getBytes(StandardCharsets.UTF_8);
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new HandlerInterceptor() {
            @Override
            public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
                // Match the resolved controller so alternate path spellings cannot bypass authentication.
                if (handler instanceof HandlerMethod method
                        && InternalUserController.class.isAssignableFrom(method.getBeanType())) {
                    String token = request.getHeader("X-Internal-Token");
                    if (token == null || !MessageDigest.isEqual(
                            internalCallToken, token.getBytes(StandardCharsets.UTF_8))) {
                        throw new UserApiException(ErrorCode.UNAUTHENTICATED);
                    }
                }
                return true;
            }
        });
    }
}
