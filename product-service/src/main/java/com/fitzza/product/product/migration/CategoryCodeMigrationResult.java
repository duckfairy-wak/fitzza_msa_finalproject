package com.fitzza.product.product.migration;

/**
 * 카테고리 이름 → 코드 변환 결과.
 *
 * @param category1Updated    대분류를 코드로 바꾼 상품 수
 * @param category2Updated    중분류를 코드로 바꾼 상품 수
 * @param subcategoryUpdated  소분류를 코드로 바꾼 상품 수
 * @param unresolvedProducts  변환 후에도 카테고리 기준 데이터에 없는 값이 남은 상품 수
 */
public record CategoryCodeMigrationResult(
        int category1Updated, int category2Updated, int subcategoryUpdated, long unresolvedProducts) {
}
