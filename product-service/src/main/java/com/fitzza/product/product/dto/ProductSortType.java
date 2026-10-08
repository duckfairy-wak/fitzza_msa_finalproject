package com.fitzza.product.product.dto;

import org.springframework.data.domain.Sort;

public enum ProductSortType {
    LATEST(Sort.by(Sort.Direction.DESC, "createdAt", "productId")),
    PRICE_ASC(Sort.by(Sort.Direction.ASC, "price").and(Sort.by(Sort.Direction.DESC, "productId"))),
    PRICE_DESC(Sort.by(Sort.Direction.DESC, "price", "productId"));

    private final Sort sort;

    ProductSortType(Sort sort) {
        this.sort = sort;
    }

    public Sort toSort() {
        return sort;
    }
}
