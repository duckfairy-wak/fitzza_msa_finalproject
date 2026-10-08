package com.fitzza.product.product.repository;

/** 상품에 저장된 카테고리 경로. 모든 값은 이름이 아니라 카테고리 코드다. */
public interface CategoryPathProjection {

    String getCategory1();

    String getCategory2();

    String getSubcategory();
}
