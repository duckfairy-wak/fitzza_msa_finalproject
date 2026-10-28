package com.fitzza.community.client;

import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

// 상품 서비스가 응답하지 않으면 RestClientException을 그대로 던진다. 확인 없이 넘어가지 않도록 호출한 쪽이 요청을 거부한다.
@Component
public class ProductServiceClient implements ProductCatalog, WorldcupResults {

    private static final ParameterizedTypeReference<List<ProductSummary>> PRODUCT_LIST =
            new ParameterizedTypeReference<>() {};

    static final String SERVICE_TOKEN_HEADER = "X-Service-Token";

    private final RestClient restClient;

    // 공용 빌더를 그대로 고치면 다른 클라이언트의 주소가 바뀌므로 복사해서 쓴다.
    public ProductServiceClient(
            @LoadBalanced RestClient.Builder restClientBuilder,
            @Value("${fitzza.product-service.base-url:http://product-service}") String baseUrl,
            @Value("${fitzza.service-token}") String serviceToken) {
        if (serviceToken == null || serviceToken.isBlank()) {
            throw new IllegalArgumentException("COMMUNITY_SERVICE_TOKEN must be set and non-blank");
        }
        this.restClient = restClientBuilder
                .clone()
                .baseUrl(baseUrl)
                .defaultHeader(SERVICE_TOKEN_HEADER, serviceToken)
                .build();
    }

    @Override
    public boolean isWishlisted(Long userId, long productId) {
        WishlistCheck check = restClient
                .get()
                .uri(uriBuilder -> uriBuilder
                        .path("/wishlists/check")
                        .queryParam("userId", userId)
                        .queryParam("itemId", productId)
                        .build())
                .retrieve()
                .body(WishlistCheck.class);
        return check != null && check.wishlisted();
    }

    @Override
    public Map<Long, String> findImageUrls(Collection<Long> productIds) {
        if (productIds.isEmpty()) {
            return Map.of();
        }
        List<ProductSummary> found = restClient
                .get()
                .uri(uriBuilder -> uriBuilder
                        .path("/products")
                        .queryParam("productIds", productIds.toArray())
                        .build())
                .retrieve()
                .body(PRODUCT_LIST);
        Map<Long, String> imageUrls = new LinkedHashMap<>();
        if (found != null) {
            for (ProductSummary product : found) {
                if (product.productId() != null && product.imageUrl() != null && !product.imageUrl().isBlank()) {
                    imageUrls.put(product.productId(), product.imageUrl());
                }
            }
        }
        return imageUrls;
    }

    @Override
    public Optional<ProductSummary> findProduct(long productId) {
        List<ProductSummary> found = restClient
                .get()
                .uri(uriBuilder -> uriBuilder
                        .path("/products")
                        .queryParam("productIds", productId)
                        .build())
                .retrieve()
                .body(PRODUCT_LIST);
        if (found == null) {
            return Optional.empty();
        }
        return found.stream()
                .filter(product -> product.productId() != null && product.productId() == productId)
                .findFirst();
    }

    // 상품 서비스는 없는 월드컵 결과에 404를 돌려준다. 남의 결과는 owned=false로 온다.
    @Override
    public Optional<WorldcupResult> findWorldcup(long worldcupHistoryId, Long userId) {
        try {
            return Optional.ofNullable(restClient
                    .get()
                    .uri(uriBuilder -> uriBuilder
                            .path("/worldcups/{worldcupHistoryId}")
                            .queryParam("userId", userId)
                            .build(worldcupHistoryId))
                    .retrieve()
                    .body(WorldcupResult.class));
        } catch (HttpClientErrorException.NotFound exception) {
            return Optional.empty();
        }
    }

    public record WishlistCheck(boolean wishlisted) {
    }
}
