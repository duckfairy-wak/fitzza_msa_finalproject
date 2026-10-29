package com.fitzza.product.product.dto;

import org.springframework.data.domain.Sort;

public enum ProductSortType {
    TIME_DESC(Sort.by(Sort.Direction.DESC, "productId")),
    PRICE_ASC(Sort.by(Sort.Direction.ASC, "price").and(Sort.by(Sort.Direction.DESC, "productId"))),
    PRICE_DESC(Sort.by(Sort.Direction.DESC, "price", "productId"));

    private final Sort sort;

    ProductSortType(Sort sort) {
        this.sort = sort;
    }

    public Sort toSort() {
        return sort;
    }

    /** 없거나 알 수 없는 값은 최신순(TIME_DESC)으로 본다. */
    public static ProductSortType from(String value) {
        if (value == null || value.isBlank()) {
            return TIME_DESC;
        }
        try {
            return ProductSortType.valueOf(value.trim());
        } catch (IllegalArgumentException exception) {
            return TIME_DESC;
        }
    }
}
