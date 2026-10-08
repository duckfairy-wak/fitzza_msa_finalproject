package com.fitzza.product.product.migration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fitzza.product.product.entity.CategoryEntity;
import com.fitzza.product.product.seed.MusinsaProductDocument;
import com.fitzza.product.product.seed.MusinsaProductMapper;
import com.fitzza.product.product.service.CategoryCatalogService;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.stereotype.Component;

/**
 * 시딩 데이터(무신사 JSON)의 카테고리 경로를 읽어 카테고리 기준 데이터(코드 ↔ 이름)를 채운다.
 * 이미 시딩된 상품의 이름을 코드로 바꾸려면 상품 시딩 이전에 저장된 카테고리도 기준 데이터에 있어야 하기 때문이다.
 */
@Slf4j
@Component
public class CategoryCatalogLoader {

    private final ResourcePatternResolver resourceResolver;
    private final ObjectMapper objectMapper;
    private final MusinsaProductMapper mapper;
    private final CategoryCatalogService categoryCatalogService;
    private final String location;

    public CategoryCatalogLoader(
            ResourcePatternResolver resourceResolver,
            ObjectMapper objectMapper,
            MusinsaProductMapper mapper,
            CategoryCatalogService categoryCatalogService,
            @Value("${fitzza.seed.musinsa.location}") String location) {
        this.resourceResolver = resourceResolver;
        this.objectMapper = objectMapper;
        this.mapper = mapper;
        this.categoryCatalogService = categoryCatalogService;
        this.location = location;
    }

    /** 새로 추가한 카테고리 수를 반환한다. 읽을 수 없는 파일은 건너뛰고 로그만 남긴다. */
    public int loadFromDataset() throws IOException {
        List<CategoryEntity> categories = new ArrayList<>();
        for (Resource resource : resourceResolver.getResources(location)) {
            try (InputStream inputStream = resource.getInputStream()) {
                MusinsaProductDocument document = objectMapper.readValue(inputStream, MusinsaProductDocument.class);
                if (document.category() != null) {
                    categories.addAll(mapper.toCategories(document));
                }
            } catch (IOException | RuntimeException exception) {
                log.warn("카테고리 추출 실패: {} ({})", resource.getDescription(), exception.getMessage());
            }
        }
        return categoryCatalogService.registerMissing(categories);
    }
}
