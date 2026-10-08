package com.fitzza.product.product.service;

import com.fitzza.product.product.entity.CategoryEntity;
import com.fitzza.product.product.repository.CategoryRepository;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 카테고리 코드·이름 기준 데이터를 관리한다. */
@Service
@RequiredArgsConstructor
public class CategoryCatalogService {

    private final CategoryRepository categoryRepository;

    /**
     * 아직 저장되지 않은 카테고리만 추가하고 추가한 건수를 반환한다. 이미 있는 코드는 이름·상위 카테고리를
     * 바꾸지 않으므로 여러 번 호출해도 안전하다.
     */
    @Transactional
    public int registerMissing(Collection<CategoryEntity> categories) {
        Map<String, CategoryEntity> candidatesByCode = new LinkedHashMap<>();
        categories.forEach(category -> candidatesByCode.putIfAbsent(category.getCategoryCode(), category));
        categoryRepository.findAllById(candidatesByCode.keySet())
                .forEach(existing -> candidatesByCode.remove(existing.getCategoryCode()));
        List<CategoryEntity> missing = List.copyOf(candidatesByCode.values());
        categoryRepository.saveAll(missing);
        return missing.size();
    }
}
