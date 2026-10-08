package com.fitzza.community.client;

import java.net.URI;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

@Component
public class UserServiceClient implements UserDirectory {

    private static final Logger log = LoggerFactory.getLogger(UserServiceClient.class);
    // user-service의 /internal API는 이 헤더의 값이 INTERNAL_CALL_TOKEN과 같아야 응답한다.
    static final String INTERNAL_TOKEN_HEADER = "X-Internal-Token";
    private static final ParameterizedTypeReference<List<UserNickname>> NICKNAME_LIST =
            new ParameterizedTypeReference<>() {};

    private final RestClient restClient;

    public UserServiceClient(
            @LoadBalanced RestClient.Builder restClientBuilder,
            @Value("${fitzza.user-service.base-url:https://user-service}") String baseUrl,
            @Value("${internal.call-token}") String internalCallToken) {
        if (internalCallToken == null || internalCallToken.isBlank()) {
            throw new IllegalArgumentException("INTERNAL_CALL_TOKEN must be set and non-blank");
        }
        URI serviceUri = URI.create(baseUrl);
        if (!"https".equalsIgnoreCase(serviceUri.getScheme()) || serviceUri.getHost() == null
                || serviceUri.getUserInfo() != null || serviceUri.getFragment() != null) {
            throw new IllegalArgumentException("fitzza.user-service.base-url must be an HTTPS URL without credentials or fragment");
        }
        this.restClient = restClientBuilder
                .baseUrl(baseUrl)
                .defaultHeader(INTERNAL_TOKEN_HEADER, internalCallToken)
                .build();
    }

    // 회원 서비스가 잠깐 죽어도 글 목록과 댓글은 보여야 하므로, 실패하면 닉네임 없이 진행한다.
    @Override
    public Map<Long, String> findNicknames(Collection<Long> userIds) {
        List<Long> distinctIds = userIds.stream().filter(Objects::nonNull).distinct().toList();
        if (distinctIds.isEmpty()) {
            return Map.of();
        }
        String joinedIds = distinctIds.stream().map(String::valueOf).collect(Collectors.joining(","));
        try {
            List<UserNickname> found = restClient
                    .get()
                    .uri(uriBuilder -> uriBuilder
                            .path("/internal/users")
                            .queryParam("userIds", joinedIds)
                            .build())
                    .retrieve()
                    .body(NICKNAME_LIST);
            if (found == null) {
                return Map.of();
            }
            return found.stream()
                    .filter(user -> user.userId() != null && user.nickname() != null)
                    .collect(Collectors.toMap(UserNickname::userId, UserNickname::nickname, (first, second) -> first));
        } catch (RestClientException exception) {
            log.warn("회원 서비스 닉네임 조회 실패, 닉네임 없이 응답합니다: {}", exception.getMessage());
            return Map.of();
        }
    }

    public record UserNickname(Long userId, String nickname) {
    }
}
