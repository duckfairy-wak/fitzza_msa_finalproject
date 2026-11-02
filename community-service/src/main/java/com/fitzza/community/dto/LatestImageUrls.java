package com.fitzza.community.dto;

import java.util.Map;

// 보여줄 때 새로 받은 이미지 주소. 상품 이미지는 상품 ID별로, 피팅 결과 이미지는 피팅 ID별로 담는다.
// 새 주소를 못 받았으면 저장된 주소를 쓴다.
public record LatestImageUrls(Map<Long, String> byProductId, Map<Long, String> byFittingId) {

    public static final LatestImageUrls NONE = new LatestImageUrls(Map.of(), Map.of());

    public LatestImageUrls {
        byProductId = byProductId == null ? Map.of() : byProductId;
        byFittingId = byFittingId == null ? Map.of() : byFittingId;
    }

    public LatestImageUrls(Map<Long, String> byProductId) {
        this(byProductId, Map.of());
    }

    public String pick(Long productId, String stored) {
        return pickFrom(byProductId, productId, stored);
    }

    public String pickFitting(Long fittingId, String stored) {
        return pickFrom(byFittingId, fittingId, stored);
    }

    private static String pickFrom(Map<Long, String> latestById, Long id, String stored) {
        if (id == null) {
            return stored;
        }
        String latest = latestById.get(id);
        return latest == null || latest.isBlank() ? stored : latest;
    }
}
