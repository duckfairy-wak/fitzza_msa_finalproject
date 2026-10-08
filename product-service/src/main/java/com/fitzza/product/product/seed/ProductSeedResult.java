package com.fitzza.product.product.seed;

/** 시딩 한 번의 처리 결과. */
public record ProductSeedResult(int imported, int skipped, int failed) {
}
