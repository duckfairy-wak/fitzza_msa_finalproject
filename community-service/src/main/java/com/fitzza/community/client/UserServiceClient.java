package com.fitzza.community.client;

import java.util.Collection;
import java.util.HashMap;
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
    // user-service는 한 번에 100명까지만 조회해 주고 넘으면 요청 전체를 거부한다.
    static final int LOOKUP_BATCH_SIZE = 100;
    private static final ParameterizedTypeReference<List<UserNickname>> NICKNAME_LIST =
            new ParameterizedTypeReference<>() {};

    private final RestClient restClient;

    public UserServiceClient(
            @LoadBalanced RestClient.Builder restClientBuilder,
            @Value("${fitzza.user-service.base-url:http://user-service}") String baseUrl,
            @Value("${internal.call-token}") String internalCallToken) {
        if (internalCallToken == null || internalCallToken.isBlank()) {
            throw new IllegalArgumentException("INTERNAL_CALL_TOKEN must be set and non-blank");
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
        Map<Long, String> nicknames = new HashMap<>();
        for (int start = 0; start < distinctIds.size(); start += LOOKUP_BATCH_SIZE) {
            int end = Math.min(start + LOOKUP_BATCH_SIZE, distinctIds.size());
            try {
                nicknames.putAll(fetchNicknames(distinctIds.subList(start, end)));
            } catch (RestClientException exception) {
                // 회원 서비스가 죽었을 때 묶음마다 타임아웃을 기다리지 않도록 남은 묶음은 건너뛴다.
                log.warn("회원 서비스 닉네임 조회 실패, 받은 닉네임만으로 응답합니다: {}", exception.getMessage());
                break;
            }
        }
        return nicknames;
    }

    private Map<Long, String> fetchNicknames(List<Long> userIds) {
        String joinedIds = userIds.stream().map(String::valueOf).collect(Collectors.joining(","));
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
    }

    public record UserNickname(Long userId, String nickname) {
    }
}
