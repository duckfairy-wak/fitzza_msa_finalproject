package com.fitzza.product.product.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 카테고리 코드와 이름의 기준 데이터. 상품은 이름이 아니라 이 테이블의 코드만 저장하고,
 * 화면에 보여줄 이름은 코드로 조회한다.
 */
@Entity
@Table(name = "category", indexes = @Index(name = "idx_category_parent", columnList = "parent_code"))
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class CategoryEntity {

    public static final int MAX_DEPTH = 3;

    @Id
    @Column(name = "category_code", length = 20)
    private String categoryCode;

    @Column(name = "category_name", nullable = false, length = 100)
    private String categoryName;

    /** 상위 카테고리 코드. 대분류(depth 1)는 null이다. */
    @Column(name = "parent_code", length = 20)
    private String parentCode;

    /** 1 = 대분류, 2 = 중분류, 3 = 소분류. */
    @Column(name = "depth", nullable = false)
    private Integer depth;

    @Builder
    private CategoryEntity(String categoryCode, String categoryName, String parentCode, Integer depth) {
        this.categoryCode = categoryCode;
        this.categoryName = categoryName;
        this.parentCode = parentCode;
        this.depth = depth;
    }
}
