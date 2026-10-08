package com.fitzza.product.product.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.MapsId;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** 상품 단위 사이즈 안내 정보. 사이즈별 실측값은 {@link OptionMeasurementEntity}에 저장한다. */
@Entity
@Table(name = "product_size_guide")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ProductSizeGuideEntity {

    @Id
    @Column(name = "product_id")
    private Long productId;

    @MapsId
    @OneToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "product_id")
    private ProductEntity product;

    /** 사이즈 표 종류. 예: 캡/야구모자 */
    @Column(name = "type_name", length = 50)
    private String typeName;

    /** 실측 단위. 예: cm */
    @Column(name = "unit", length = 10)
    private String unit;

    @Column(name = "description", length = 500)
    private String description;

    @Column(name = "guide_image_url", length = 500)
    private String guideImageUrl;

    @Builder
    private ProductSizeGuideEntity(
            ProductEntity product, String typeName, String unit, String description, String guideImageUrl) {
        this.product = product;
        this.typeName = typeName;
        this.unit = unit;
        this.description = description;
        this.guideImageUrl = guideImageUrl;
    }
}
