package com.fitzza.product.product.migration;

import com.fitzza.product.product.repository.ProductRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 상품에 한글 이름으로 저장된 카테고리를 카테고리 테이블의 코드로 일괄 변환한다.
 * 카테고리 테이블이 먼저 채워져 있어야 하며, 이미 코드인 값은 건드리지 않아 여러 번 실행해도 안전하다.
 */
@Service
@RequiredArgsConstructor
public class CategoryCodeMigrationService {

    private final ProductRepository productRepository;

    /** 카테고리 기준 데이터에 없는 값(변환되지 않은 이름 등)이 저장된 상품이 있는지 확인한다. */
    @Transactional(readOnly = true)
    public boolean hasUnresolvedProducts() {
        return productRepository.countWithUnknownCategoryCode() > 0;
    }

    /** 상위 코드로 하위 카테고리를 찾으므로 대분류 → 중분류 → 소분류 순서를 지켜야 한다. 전체가 한 트랜잭션이다. */
    @Transactional
    public CategoryCodeMigrationResult migrate() {
        int category1Updated = productRepository.replaceCategory1NameWithCode();
        int category2Updated = productRepository.replaceCategory2NameWithCode();
        int subcategoryUpdated = productRepository.replaceSubcategoryNameWithCode();
        return new CategoryCodeMigrationResult(
                category1Updated, category2Updated, subcategoryUpdated, productRepository.countWithUnknownCategoryCode());
    }
}
