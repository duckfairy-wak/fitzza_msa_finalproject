package com.fitzza.community.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;

// 공유한 순간의 대상 정보를 글에 복사해 둔다. 원본 상품이 바뀌거나 내려가도 글에는 공유 당시 모습이 남는다.
// 월드컵은 우승 상품 정보를 담는다. 코디는 총 가격·첫 상품 이미지·조화도 요약을, 피팅은 결과 이미지를 담고
// 코디·피팅에 들어 있던 상품 목록은 글의 sharedItems에 따로 저장한다.
@Embeddable
public class SharedSnapshot {

    @Column(name = "shared_product_id")
    private Long productId;

    @Column(name = "shared_brand_name", length = 100)
    private String brandName;

    @Column(name = "shared_product_name", length = 255)
    private String productName;

    @Column(name = "shared_price")
    private Integer price;

    @Column(name = "shared_image_url", columnDefinition = "text")
    private String imageUrl;

    // 추천 코디의 조화도 요약(feedbackSummary). 월드컵·피팅은 비어 있다.
    @Column(name = "shared_summary", columnDefinition = "text")
    private String summary;

    protected SharedSnapshot() {
    }

    public SharedSnapshot(Long productId, String brandName, String productName, Integer price, String imageUrl) {
        this(productId, brandName, productName, price, imageUrl, null);
    }

    public SharedSnapshot(
            Long productId, String brandName, String productName, Integer price, String imageUrl, String summary) {
        this.productId = productId;
        this.brandName = brandName;
        this.productName = productName;
        this.price = price;
        this.imageUrl = imageUrl;
        this.summary = summary;
    }

    public Long getProductId() {
        return productId;
    }

    public String getBrandName() {
        return brandName;
    }

    public String getProductName() {
        return productName;
    }

    public Integer getPrice() {
        return price;
    }

    public String getImageUrl() {
        return imageUrl;
    }

    public String getSummary() {
        return summary;
    }
}
