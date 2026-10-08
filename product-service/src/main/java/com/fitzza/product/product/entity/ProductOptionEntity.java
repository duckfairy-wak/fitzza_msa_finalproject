package com.fitzza.product.product.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.ColumnDefault;

@Entity
@Table(name = "product_option")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ProductOptionEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "option_id")
    private Long optionId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "product_id", nullable = false)
    private ProductEntity product;

    /** 원천 쇼핑몰의 옵션(SKU) ID. 직접 등록한 옵션은 null이다. */
    @Column(name = "source_option_id", unique = true)
    private Long sourceOptionId;

    /** 원천 데이터의 옵션 관리 코드. 예: BLACK - M */
    @Column(name = "managed_code", length = 100)
    private String managedCode;

    @Column(name = "color", length = 100)
    private String color;

    @Column(name = "size", length = 100)
    private String size;

    /** 상품 가격에 더해지는 옵션 추가 금액(원). */
    @ColumnDefault("0")
    @Column(name = "additional_price", nullable = false)
    private Integer additionalPrice;

    @Builder
    private ProductOptionEntity(
            ProductEntity product,
            Long sourceOptionId,
            String managedCode,
            String color,
            String size,
            Integer additionalPrice) {
        this.product = product;
        this.sourceOptionId = sourceOptionId;
        this.managedCode = managedCode;
        this.color = color;
        this.size = size;
        this.additionalPrice = additionalPrice == null ? 0 : additionalPrice;
    }

    /** 상품 가격에 옵션 추가 금액을 더한 실제 판매가를 계산한다. */
    public int calculatePrice() {
        return product.getPrice() + additionalPrice;
    }
}
