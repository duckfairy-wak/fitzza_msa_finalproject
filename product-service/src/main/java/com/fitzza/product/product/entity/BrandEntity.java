package com.fitzza.product.product.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(name = "brand")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class BrandEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "brand_id")
    private Long brandId;

    @Column(name = "brand_name", nullable = false, unique = true, length = 100)
    private String brandName;

    /** 영문 브랜드명. 원천 데이터에 없으면 null이다. */
    @Column(name = "brand_name_en", length = 100)
    private String brandNameEn;

    /** 원천 쇼핑몰의 브랜드 식별 코드(예: chaptereight). 직접 등록한 브랜드는 null이다. */
    @Column(name = "brand_code", unique = true, length = 100)
    private String brandCode;

    @Builder
    private BrandEntity(String brandName, String brandNameEn, String brandCode) {
        this.brandName = brandName;
        this.brandNameEn = brandNameEn;
        this.brandCode = brandCode;
    }
}
