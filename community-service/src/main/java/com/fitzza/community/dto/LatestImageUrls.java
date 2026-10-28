package com.fitzza.community.dto;

import java.util.Map;

// 상품 ID별로 새로 받은 이미지 주소. 상품 ID가 없거나(피팅 결과 등) 새 주소를 못 받았으면 저장된 주소를 쓴다.
public record LatestImageUrls(Map<Long, String> byProductId) {

    public static final LatestImageUrls NONE = new LatestImageUrls(Map.of());

    public LatestImageUrls {
        byProductId = byProductId == null ? Map.of() : byProductId;
    }

    public String pick(Long productId, String stored) {
        if (productId == null) {
            return stored;
        }
        String latest = byProductId.get(productId);
        return latest == null || latest.isBlank() ? stored : latest;
    }
}
