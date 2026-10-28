package com.fitzza.community.service;

import com.fitzza.community.client.ProductCatalog;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

// 글에 복사해 둔 상품 이미지 주소 대신, 보여줄 때마다 상품 서비스에서 지금 쓸 수 있는 주소를 받는다.
// 상품 이미지는 1시간짜리 Presigned URL이라 저장된 주소는 곧 만료된다.
// 상품 서비스가 응답하지 않으면 글 조회까지 막지 않고, 저장된 주소를 그대로 보여준다.
@Component
public class ProductImages {

    // 상품 서비스 내부 일괄 조회가 한 번에 받는 ID 수(PagingConstants.MAX_INTERNAL_IDS)와 같다.
    static final int MAX_IDS_PER_REQUEST = 100;

    private static final Logger log = LoggerFactory.getLogger(ProductImages.class);

    private final ProductCatalog productCatalog;

    public ProductImages(ProductCatalog productCatalog) {
        this.productCatalog = productCatalog;
    }

    public Map<Long, String> latest(Collection<Long> productIds) {
        List<Long> ids = productIds.stream().filter(Objects::nonNull).distinct().toList();
        if (ids.isEmpty()) {
            return Map.of();
        }
        Map<Long, String> imageUrls = new HashMap<>();
        try {
            for (int from = 0; from < ids.size(); from += MAX_IDS_PER_REQUEST) {
                imageUrls.putAll(productCatalog.findImageUrls(
                        ids.subList(from, Math.min(from + MAX_IDS_PER_REQUEST, ids.size()))));
            }
        } catch (RuntimeException exception) {
            log.warn("상품 이미지 주소를 새로 받지 못해 저장된 주소를 씁니다: {}", exception.getMessage());
            return Map.of();
        }
        return imageUrls;
    }
}
