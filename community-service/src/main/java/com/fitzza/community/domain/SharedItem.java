package com.fitzza.community.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Embeddable;

// 공유한 코디·피팅 결과에 들어 있던 상품 하나를 공유 당시 모습대로 복사해 둔다.
@Embeddable
public class SharedItem {

    @Column(name = "product_id")
    private Long productId;

    @Column(name = "product_name", length = 255)
    private String productName;

    @Column(name = "price")
    private Integer price;

    @Column(name = "image_url", columnDefinition = "text")
    private String imageUrl;

    protected SharedItem() {
    }

    public SharedItem(Long productId, String productName, Integer price, String imageUrl) {
        this.productId = productId;
        this.productName = productName;
        this.price = price;
        this.imageUrl = imageUrl;
    }

    public Long getProductId() {
        return productId;
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
}
