package com.fitzza.community.client;

import java.util.Collection;
import java.util.Map;
import java.util.Optional;

// 투표 선택지나 공유 글로 고른 찜 상품을 상품 서비스에서 확인하는 자리. 테스트에서는 가짜 구현으로 바꿔 끼운다.
public interface ProductCatalog {

    boolean isWishlisted(Long userId, long productId);

    Optional<ProductSummary> findProduct(long productId);

    // 글을 보여줄 때 상품 이미지 주소를 새로 받는다. 상품 서비스의 이미지는 만료되는 Presigned URL이라
    // 공유 당시 복사해 둔 주소는 시간이 지나면 열리지 않는다. 없는 상품은 결과에서 빠진다.
    default Map<Long, String> findImageUrls(Collection<Long> productIds) {
        return Map.of();
    }

    record ProductSummary(
            Long productId, String brandName, String productName, Integer price, String imageUrl, String status) {
    }
}
