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
import jakarta.persistence.UniqueConstraint;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(name = "product_image", uniqueConstraints = @UniqueConstraint(
        name = "uk_product_image_sequence", columnNames = {"product_id", "sequence"}))
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ProductImageEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "image_id")
    private Long imageId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "product_id", nullable = false)
    private ProductEntity product;

    @Column(name = "image_url", nullable = false, length = 500)
    private String imageUrl;

    /** 노출 순서(0부터 시작). 0번이 대표 이미지다. */
    @Column(name = "sequence", nullable = false)
    private Integer sequence;

    @Builder
    private ProductImageEntity(ProductEntity product, String imageUrl, Integer sequence) {
        this.product = product;
        this.imageUrl = imageUrl;
        this.sequence = sequence;
    }
}
