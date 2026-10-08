package com.fitzza.product.product.migration;

import java.io.IOException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

/**
 * 기존 상품에 한글 이름으로 저장된 카테고리를 기동할 때 코드로 바꾼다. 카테고리 기준 데이터에 없는 값을 가진
 * 상품이 없으면 아무것도 하지 않으므로 평소 기동에는 조회 쿼리 한 번만 추가된다. 상품 시딩보다 먼저 실행된다.
 * 끄려면 {@code fitzza.migration.category-code.enabled=false}(환경변수 CATEGORY_CODE_MIGRATION_ENABLED)로 설정한다.
 *
 * <p>변환은 멱등이라 여러 번 실행해도 데이터가 바뀌지 않는다. 실패해도 서비스 기동은 막지 않고 로그만 남긴다.
 */
@Slf4j
@Component
@Order(1)
@RequiredArgsConstructor
@ConditionalOnProperty(
        prefix = "fitzza.migration.category-code", name = "enabled", havingValue = "true", matchIfMissing = true)
public class CategoryCodeMigrationRunner implements CommandLineRunner {

    private final CategoryCatalogLoader categoryCatalogLoader;
    private final CategoryCodeMigrationService migrationService;

    @Override
    public void run(String... args) {
        try {
            if (!migrationService.hasUnresolvedProducts()) {
                return;
            }
            int loadedCategories = categoryCatalogLoader.loadFromDataset();
            CategoryCodeMigrationResult result = migrationService.migrate();
            log.info("카테고리 코드 마이그레이션 완료: 카테고리 추가 {}건, 대분류 {}건 / 중분류 {}건 / 소분류 {}건 변환",
                    loadedCategories, result.category1Updated(), result.category2Updated(),
                    result.subcategoryUpdated());
            if (result.unresolvedProducts() > 0) {
                log.warn("카테고리 코드로 변환하지 못한 상품이 {}건 남았습니다. 해당 상품은 카테고리 목록에 노출되지 않습니다.",
                        result.unresolvedProducts());
            }
        } catch (IOException | RuntimeException exception) {
            log.error("카테고리 코드 마이그레이션에 실패했습니다. 상품 변환은 롤백되었습니다.", exception);
        }
    }
}
