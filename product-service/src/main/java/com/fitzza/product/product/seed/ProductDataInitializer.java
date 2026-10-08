package com.fitzza.product.product.seed;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fitzza.product.product.repository.ProductRepository;
import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.Set;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.stereotype.Component;

/**
 * 애플리케이션 시작 시 무신사 크롤링 JSON을 읽어 저장한다. 읽을 위치는 {@code fitzza.seed.musinsa.location}이며
 * 기본값은 resources의 final_products 하위(모자, 상의 등 하위 폴더 포함) JSON 전체다.
 *
 * <p>이미 저장된 상품(source + source_product_id가 같은 상품)은 건너뛰므로 재시작해도 중복 저장되지 않는다.
 * 파일 하나가 잘못되어도 나머지 파일은 계속 처리한다. 끄려면 {@code fitzza.seed.musinsa.enabled=false}로 설정한다.
 */
@Slf4j
@Component
@ConditionalOnProperty(prefix = "fitzza.seed.musinsa", name = "enabled", havingValue = "true", matchIfMissing = true)
public class ProductDataInitializer implements CommandLineRunner {

    private final ResourcePatternResolver resourceResolver;
    private final ObjectMapper objectMapper;
    private final ProductRepository productRepository;
    private final ProductSeedService productSeedService;
    private final String location;

    public ProductDataInitializer(
            ResourcePatternResolver resourceResolver,
            ObjectMapper objectMapper,
            ProductRepository productRepository,
            ProductSeedService productSeedService,
            @Value("${fitzza.seed.musinsa.location}") String location) {
        this.resourceResolver = resourceResolver;
        this.objectMapper = objectMapper;
        this.productRepository = productRepository;
        this.productSeedService = productSeedService;
        this.location = location;
    }

    /** 시딩 실패가 서비스 기동을 막지 않도록 리소스 조회 오류는 로그만 남기고 넘어간다. */
    @Override
    public void run(String... args) {
        try {
            ProductSeedResult result = seedProducts();
            log.info("무신사 상품 시딩 완료: 저장 {}건, 기존 데이터로 건너뜀 {}건, 실패 {}건",
                    result.imported(), result.skipped(), result.failed());
        } catch (IOException exception) {
            log.warn("무신사 상품 시딩 파일을 찾지 못했습니다. location={} ({})", location, exception.getMessage());
        }
    }

    public ProductSeedResult seedProducts() throws IOException {
        Resource[] resources = resourceResolver.getResources(location);
        if (resources.length == 0) {
            log.info("무신사 상품 시딩 파일이 없어 건너뜁니다. location={}", location);
            return new ProductSeedResult(0, 0, 0);
        }
        Resource[] sortedResources = Arrays.stream(resources)
                .sorted(Comparator.comparing(Resource::getDescription))
                .toArray(Resource[]::new);
        Set<Long> savedSourceIds = new HashSet<>(productRepository.findSourceProductIds(MusinsaProductMapper.SOURCE));

        int imported = 0;
        int skipped = 0;
        int failed = 0;
        for (Resource resource : sortedResources) {
            try {
                MusinsaProductDocument document = readDocument(resource);
                if (savedSourceIds.contains(document.productId())) {
                    skipped++;
                    continue;
                }
                productSeedService.saveProduct(document);
                savedSourceIds.add(document.productId());
                imported++;
            } catch (IOException | RuntimeException exception) {
                failed++;
                log.warn("무신사 상품 시딩 실패: {} ({})", resource.getDescription(), exception.getMessage());
            }
        }
        return new ProductSeedResult(imported, skipped, failed);
    }

    private MusinsaProductDocument readDocument(Resource resource) throws IOException {
        try (InputStream inputStream = resource.getInputStream()) {
            return objectMapper.readValue(inputStream, MusinsaProductDocument.class);
        }
    }
}
